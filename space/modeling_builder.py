from __future__ import annotations

import base64
import json
import re
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Optional

from huggingface_hub import InferenceClient
from PIL import Image

from minecraft_builder import BlockSmithError, KIMI_MODEL, resolve_minecraft_version

MAX_MODEL_ATTEMPTS = 3
MAX_REFERENCE_IMAGE_BYTES = 8_000_000
MAX_TEXTURE_SIZE = 64
MAX_TEXT_FILE_BYTES = 900_000
MAX_PROJECT_TEXT_BYTES = 12_000_000

MODEL_FORMATS = [
    "Java block/item model",
    "Blockbench (.bbmodel)",
    "GeckoLib model + animation",
    "Modded entity model",
]

MODEL_SYSTEM_PROMPT = r"""
You are BlockSmith's Minecraft 3D modeling specialist. You can inspect an optional reference image.
Create Minecraft-ready model geometry, UV layout, animation data, and small pixel textures when useful.

Return ONE strict JSON object and nothing else:
{
  "summary": "short description",
  "warnings": ["optional warnings"],
  "files": [
    {"path": "relative/path.ext", "content": "full UTF-8 text file"}
  ],
  "textures": [
    {
      "path": "relative/path.png",
      "width": 16,
      "height": 16,
      "pixels": [
        ["#RRGGBB", "#RRGGBBAA", "..."],
        ["..."]
      ]
    }
  ]
}

Rules:
- Never use absolute paths or ../ paths.
- Geometry must be practical for Minecraft, not just descriptive prose.
- For Java block/item models, output valid Minecraft Java model JSON with elements/faces/UVs as needed.
  Place runtime files under an assets/<namespace>/models/... layout when appropriate.
- For Blockbench output, include a .bbmodel project. .bbmodel is JSON-based. Include meta.format_version,
  elements/groups/outliner as appropriate, and coherent UUID references. Also include a practical exported
  Minecraft/GeckoLib runtime JSON when the selected target needs one.
- For GeckoLib output, include valid geo/*.geo.json and animations/*.animation.json files when animation is requested.
  Include bones, pivots, cubes, UVs, and animation channels that match by bone name.
- For a modded entity model, include the model asset files and any small Java model/renderer source needed to use them,
  but do not invent unrelated gameplay code.
- Make UVs usable and non-overlapping where practical. Keep pivots sensible for animation.
- Use the reference image as visual guidance if provided. Reconstruct recognizable proportions and major details,
  but do not claim exact visual reproduction if the image does not reveal hidden sides.
- Pixel textures are optional. If you generate them, use the textures array above. Prefer 16x16 or 32x32.
  Do not exceed 64x64. Every row must contain exactly width colors and there must be exactly height rows.
- Use #RRGGBB or #RRGGBBAA pixel colors. Transparency is allowed.
- Generated text files may reference texture PNGs created by the textures array.
- No base64 blobs inside files. No secrets, telemetry, remote-control code, self-updaters, or runtime downloading.
"""

MODEL_REPAIR_PROMPT = r"""
Repair this generated Minecraft model project after BlockSmith validation failed.
Return ONE strict JSON object using the same schema: summary, warnings, files, textures.
Return the COMPLETE corrected model project, not a patch.
Preserve the user's requested appearance and target format. Fix malformed JSON, broken references, invalid UV/geometry
structures, mismatched GeckoLib bone/animation names, and invalid texture grids reported by the validator.
"""


def _safe_relpath(name: str) -> Optional[str]:
    name = (name or "").replace("\\", "/").lstrip("/")
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or len(p.parts) > 24:
        return None
    return str(p)


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        first, last = text.find("{"), text.rfind("}")
        if first >= 0 and last > first:
            try:
                return json.loads(text[first:last + 1])
            except json.JSONDecodeError:
                pass
    raise BlockSmithError("Kimi returned modeling output that was not valid project JSON.")


def _prepare_reference_image(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise BlockSmithError("The reference image could not be read.")
    if p.stat().st_size > MAX_REFERENCE_IMAGE_BYTES:
        raise BlockSmithError("Reference image is too large. Please use an image under 8 MB.")
    try:
        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((1024, 1024))
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=88, optimize=True)
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        raise BlockSmithError(f"Reference image could not be decoded: {type(exc).__name__}: {exc}") from exc
    return f"data:image/jpeg;base64,{encoded}"


def _call_kimi(client: InferenceClient, system: str, payload: str, image_url: Optional[str]) -> dict:
    user_content = [{"type": "text", "text": payload}]
    if image_url:
        user_content.insert(0, {"type": "image_url", "image_url": {"url": image_url}})
    try:
        response = client.chat.completions.create(
            model=KIMI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            max_tokens=24000,
            temperature=0.18,
        )
        return _extract_json(response.choices[0].message.content)
    except BlockSmithError:
        raise
    except Exception as exc:
        msg = str(exc).strip() or repr(exc)
        low = msg.lower()
        hint = ""
        if "402" in msg or "credit" in low or "payment" in low:
            hint = " Your Hugging Face Inference Providers credits may be exhausted."
        elif "429" in msg or "rate" in low:
            hint = " The inference provider is rate-limiting this request."
        elif "401" in msg or "403" in msg or "unauthor" in low or "forbidden" in low:
            hint = " Sign out/in to Hugging Face and confirm inference access."
        raise BlockSmithError(f"Kimi K3 modeling inference failed: {type(exc).__name__}: {msg}.{hint}") from exc


def _sanitize_files(raw_files) -> tuple[dict[str, str], list[str]]:
    if not isinstance(raw_files, list):
        raise BlockSmithError("Kimi's modeling response did not contain a files list.")
    out: dict[str, str] = {}
    warnings: list[str] = []
    total = 0
    for item in raw_files[:350]:
        if not isinstance(item, dict):
            continue
        path = _safe_relpath(str(item.get("path", "")))
        content = item.get("content")
        if not path or not isinstance(content, str):
            warnings.append("Dropped an invalid model file entry.")
            continue
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_TEXT_FILE_BYTES:
            warnings.append(f"Dropped oversized model file: {path}")
            continue
        total += len(encoded)
        if total > MAX_PROJECT_TEXT_BYTES:
            warnings.append("Model project exceeded the 12 MB text limit; remaining files were dropped.")
            break
        out[path] = content
    if not out:
        raise BlockSmithError("Kimi returned no usable model files.")
    return out, warnings


def _parse_color(value: str) -> tuple[int, int, int, int]:
    text = str(value).strip().lstrip("#")
    if len(text) == 6:
        text += "FF"
    if len(text) != 8 or not re.fullmatch(r"[0-9A-Fa-f]{8}", text):
        raise ValueError(f"invalid pixel color {value!r}")
    return tuple(int(text[i:i + 2], 16) for i in range(0, 8, 2))


def _render_textures(raw_textures) -> tuple[dict[str, bytes], list[str]]:
    if raw_textures in (None, []):
        return {}, []
    if not isinstance(raw_textures, list):
        return {}, ["Ignored textures because Kimi returned a non-list textures field."]
    outputs: dict[str, bytes] = {}
    warnings: list[str] = []
    for item in raw_textures[:24]:
        if not isinstance(item, dict):
            continue
        path = _safe_relpath(str(item.get("path", "")))
        if not path or not path.lower().endswith(".png"):
            warnings.append("Dropped a generated texture with an invalid .png path.")
            continue
        try:
            width = int(item.get("width", 0))
            height = int(item.get("height", 0))
        except Exception:
            warnings.append(f"Dropped {path}: width/height were not integers.")
            continue
        if not (1 <= width <= MAX_TEXTURE_SIZE and 1 <= height <= MAX_TEXTURE_SIZE):
            warnings.append(f"Dropped {path}: texture dimensions must be 1-{MAX_TEXTURE_SIZE}px.")
            continue
        rows = item.get("pixels")
        if not isinstance(rows, list) or len(rows) != height:
            warnings.append(f"Dropped {path}: expected exactly {height} pixel rows.")
            continue
        pixels = []
        failed = None
        for y, row in enumerate(rows):
            if isinstance(row, str):
                row = row.split()
            if not isinstance(row, list) or len(row) != width:
                failed = f"row {y} does not contain {width} colors"
                break
            try:
                pixels.extend(_parse_color(c) for c in row)
            except ValueError as exc:
                failed = str(exc)
                break
        if failed:
            warnings.append(f"Dropped {path}: {failed}.")
            continue
        im = Image.new("RGBA", (width, height))
        im.putdata(pixels)
        buf = BytesIO()
        im.save(buf, format="PNG", optimize=True)
        outputs[path] = buf.getvalue()
    return outputs, warnings


def _validate_json_file(path: str, content: str, generated_paths: set[str]) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(content)
    except Exception as exc:
        return [f"{path}: invalid JSON: {exc}"]
    low = path.lower()

    if low.endswith(".bbmodel"):
        if not isinstance(data, dict):
            errors.append(f"{path}: .bbmodel root must be an object.")
        else:
            meta = data.get("meta")
            if not isinstance(meta, dict) or not meta.get("format_version"):
                errors.append(f"{path}: .bbmodel is missing meta.format_version.")
            if not isinstance(data.get("elements", []), list):
                errors.append(f"{path}: .bbmodel elements must be a list.")
            if "outliner" in data and not isinstance(data.get("outliner"), list):
                errors.append(f"{path}: .bbmodel outliner must be a list.")

    if "/models/block/" in low or "/models/item/" in low or low.startswith("models/"):
        if not isinstance(data, dict) or not (data.get("parent") or isinstance(data.get("elements"), list)):
            errors.append(f"{path}: Java model JSON should contain a parent or an elements list.")
        if isinstance(data, dict):
            elements = data.get("elements", [])
            if isinstance(elements, list):
                for i, element in enumerate(elements):
                    if not isinstance(element, dict):
                        errors.append(f"{path}: element {i} must be an object.")
                        continue
                    for field in ("from", "to"):
                        if field in element and (
                            not isinstance(element[field], list)
                            or len(element[field]) != 3
                            or not all(isinstance(n, (int, float)) for n in element[field])
                        ):
                            errors.append(f"{path}: element {i}.{field} must be a 3-number array.")

    if low.endswith(".geo.json") or "/geo/" in low:
        if not isinstance(data, dict) or not isinstance(data.get("minecraft:geometry"), list):
            errors.append(f"{path}: GeckoLib geometry JSON is missing minecraft:geometry[].")

    if "animation" in low and low.endswith(".json"):
        if not isinstance(data, dict) or not isinstance(data.get("animations"), dict):
            errors.append(f"{path}: animation JSON is missing an animations object.")

    if isinstance(data, dict):
        textures = data.get("textures")
        if isinstance(textures, dict):
            for name, ref in textures.items():
                if not isinstance(ref, str) or ref.startswith("#") or ref.startswith("minecraft:"):
                    continue
                if ":" in ref:
                    namespace, tex = ref.split(":", 1)
                    candidate = f"assets/{namespace}/textures/{tex}.png"
                    if candidate not in generated_paths:
                        errors.append(f"{path}: texture '{name}' references missing generated file {candidate}.")
    return errors


def validate_model_project(files: dict[str, str], textures: dict[str, bytes], model_format: str) -> tuple[bool, str]:
    generated_paths = set(files) | set(textures)
    errors: list[str] = []
    notes: list[str] = []
    modelish = 0

    for path, content in files.items():
        low = path.lower()
        if low.endswith(".json") or low.endswith(".bbmodel"):
            modelish += 1
            errors.extend(_validate_json_file(path, content, generated_paths))
        elif low.endswith(".obj"):
            modelish += 1
            lines = content.splitlines()
            if not any(line.startswith("v ") for line in lines) or not any(line.startswith("f ") for line in lines):
                errors.append(f"{path}: OBJ needs both vertex (v) and face (f) records.")
        elif low.endswith(".mtl"):
            modelish += 1

    if modelish == 0:
        errors.append("No recognized model file (.json, .bbmodel, .obj, .mtl) was generated.")

    if model_format == "Blockbench (.bbmodel)" and not any(p.lower().endswith(".bbmodel") for p in files):
        errors.append("Blockbench target requires a .bbmodel source project.")
    if model_format == "GeckoLib model + animation":
        if not any(p.lower().endswith(".geo.json") or "/geo/" in p.lower() for p in files):
            errors.append("GeckoLib target requires a geometry JSON file.")
        if not any("animation" in p.lower() and p.lower().endswith(".json") for p in files):
            notes.append("No animation JSON was generated; this is acceptable only if the requested model is static.")
    if model_format == "Java block/item model":
        if not any("/models/" in p.lower() and p.lower().endswith(".json") for p in files):
            errors.append("Java block/item target requires a runtime model JSON under a models/ path.")

    if textures:
        notes.append(f"Validated {len(textures)} generated PNG texture(s).")
    else:
        notes.append("No raster texture was generated; model may reference vanilla/external textures or require texturing later.")

    if errors:
        return False, "BlockSmith model validation FAILED:\n- " + "\n- ".join(errors + notes)
    return True, "BlockSmith model validation passed.\n- " + "\n- ".join(notes)


def _write_model_zip(project_name: str, files: dict[str, str], textures: dict[str, bytes], info: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "minecraft-model"
    out_dir = Path(tempfile.mkdtemp(prefix="blocksmith-model-"))
    out_path = out_dir / f"{safe_name}-model.zip"
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as zf:
        for path, content in sorted(files.items()):
            zf.writestr(path, content)
        for path, content in sorted(textures.items()):
            zf.writestr(path, content)
        zf.writestr("BLOCKSMITH_MODEL_INFO.txt", info)
    return str(out_path)


def build_model_project(
    *,
    project_name: str,
    model_format: str,
    minecraft_version: str,
    user_prompt: str,
    reference_image,
    hf_token: str,
):
    if not hf_token:
        raise BlockSmithError("No Hugging Face OAuth token was received. Sign in with Hugging Face and try again.")
    if not user_prompt or len(user_prompt.strip()) < 6:
        raise BlockSmithError("Describe the model you want in a little more detail.")
    if model_format not in MODEL_FORMATS:
        raise BlockSmithError(f"Unknown model target: {model_format}")

    mc = resolve_minecraft_version(minecraft_version)
    image_url = _prepare_reference_image(reference_image)
    client = InferenceClient(provider="auto", api_key=hf_token, timeout=180)
    payload = json.dumps(
        {
            "project_name": (project_name or "MinecraftModel")[:80],
            "model_format": model_format,
            "minecraft_version": mc,
            "request": user_prompt,
            "reference_image_supplied": bool(image_url),
            "goal": "Produce actual editable Minecraft geometry/animation assets, UVs, and small textures where useful.",
        },
        ensure_ascii=False,
    )

    warnings: list[str] = []
    logs: list[str] = [
        f"Model: {KIMI_MODEL}",
        f"Target: {model_format} / Minecraft {mc}",
        f"Reference image: {'yes' if image_url else 'no'}",
    ]
    parsed = _call_kimi(client, MODEL_SYSTEM_PROMPT, payload, image_url)

    final_files: dict[str, str] = {}
    final_textures: dict[str, bytes] = {}
    valid = False
    summary = str(parsed.get("summary") or f"Generated {project_name} model.")

    for attempt in range(1, MAX_MODEL_ATTEMPTS + 1):
        files, file_warnings = _sanitize_files(parsed.get("files"))
        textures, texture_warnings = _render_textures(parsed.get("textures"))
        warnings.extend(parsed.get("warnings") or [])
        warnings.extend(file_warnings)
        warnings.extend(texture_warnings)

        valid, validation_log = validate_model_project(files, textures, model_format)
        logs.append(f"\n=== Model validation attempt {attempt}/{MAX_MODEL_ATTEMPTS} ===\n{validation_log}")
        final_files, final_textures = files, textures
        if valid:
            break
        if attempt < MAX_MODEL_ATTEMPTS:
            repair_payload = json.dumps(
                {
                    "project_name": project_name,
                    "model_format": model_format,
                    "minecraft_version": mc,
                    "original_request": user_prompt,
                    "validation_errors": validation_log,
                    "current_files": [{"path": p, "content": c} for p, c in files.items()],
                    "current_texture_specs": parsed.get("textures") or [],
                    "reference_image_supplied": bool(image_url),
                },
                ensure_ascii=False,
            )
            parsed = _call_kimi(client, MODEL_REPAIR_PROMPT, repair_payload, image_url)
            summary = str(parsed.get("summary") or summary)

    status = (
        f"Generated **{len(final_files)} model/source files**"
        + (f" and **{len(final_textures)} PNG texture(s)**" if final_textures else "")
        + f" for **Minecraft {mc}** using **{model_format}**.\n\n"
    )
    if valid:
        status += "✅ **Model validation passed.** Geometry/model JSON and generated texture data passed BlockSmith's structural checks."
    else:
        status += "⚠️ **Model validation still reports issues after automatic repair attempts.** The ZIP is provided with the full validation log so it can be inspected."
    if image_url:
        status += "\n\n🖼️ Kimi used the uploaded reference image as visual guidance."
    status += (
        "\n\nVisual note: structural validation cannot prove that every angle looks perfect inside Minecraft. "
        "Open the included `.bbmodel` in Blockbench or test the runtime model in-game for final artistic review."
    )
    if warnings:
        unique = list(dict.fromkeys(str(w) for w in warnings if w))
        status += "\n\n**Warnings / notes:**\n" + "\n".join(f"- {w}" for w in unique[:18])

    log = "\n".join(logs)
    output = _write_model_zip(project_name, final_files, final_textures, status.replace("**", "") + "\n\n" + log)
    manifest = {
        "model": KIMI_MODEL,
        "minecraft_version": mc,
        "artifact_kind": "3D model / animation",
        "model_format": model_format,
        "reference_image_used": bool(image_url),
        "validated": valid,
        "summary": summary,
        "text_files": sorted(final_files),
        "textures": sorted(final_textures),
        "outputs": [Path(output).name],
        "warnings": list(dict.fromkeys(str(w) for w in warnings if w)),
    }
    return status, [output], manifest, log
