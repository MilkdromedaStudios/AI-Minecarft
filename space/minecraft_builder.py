from __future__ import annotations

import json
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional
from xml.etree import ElementTree

import requests
from huggingface_hub import InferenceClient

KIMI_MODEL = "moonshotai/Kimi-K3"

MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FABRIC_GAMES = "https://meta.fabricmc.net/v2/versions/game"
QUILT_GAMES = "https://meta.quiltmc.org/v3/versions/game"
PAPER_PROJECT = "https://api.papermc.io/v2/projects/paper"
PURPUR_PROJECT = "https://api.purpurmc.org/v2/purpur"
FORGE_META = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
NEOFORGE_META = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"

MAX_IMPORT_FILES = 220
MAX_IMPORT_BYTES = 3_000_000
MAX_SINGLE_TEXT = 120_000
ALLOWED_TEXT_SUFFIXES = {
    ".java", ".kt", ".kts", ".json", ".mcmeta", ".toml", ".yaml", ".yml", ".xml",
    ".properties", ".gradle", ".md", ".txt", ".glsl", ".fsh", ".vsh", ".gsh",
    ".cfg", ".conf", ".js", ".ts", ".py", ".css", ".html", ".lang", ".mcfunction",
}
RISKY_BUILD_NAMES = {
    "gradlew", "gradlew.bat", "build.gradle", "build.gradle.kts",
    "settings.gradle", "settings.gradle.kts", "pom.xml",
}


def _get_json(url: str, timeout: float = 8.0):
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "BlockSmith-HF-Space/1.0"})
    r.raise_for_status()
    return r.json()


def list_minecraft_versions() -> list[str]:
    """Return all Mojang Java versions, newest first, including snapshots."""
    try:
        data = _get_json(MOJANG_MANIFEST)
        return [v["id"] for v in data.get("versions", []) if v.get("id")]
    except Exception:
        return ["latest"]


def _xml_versions(url: str) -> list[str]:
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "BlockSmith-HF-Space/1.0"})
        r.raise_for_status()
        root = ElementTree.fromstring(r.text)
        return [n.text for n in root.findall(".//version") if n.text]
    except Exception:
        return []


def loader_note(loader: str, version: str) -> str:
    """Best-effort live compatibility hint; generation can still proceed."""
    if not loader or loader == "Vanilla / N/A":
        return "✅ Vanilla-format target; no mod-loader compatibility check is needed."
    if not version or version == "latest":
        return "ℹ️ Pick a concrete Minecraft version to run a loader compatibility check."

    try:
        if loader == "Fabric":
            games = _get_json(FABRIC_GAMES)
            ok = any(x.get("version") == version for x in games)
        elif loader == "Quilt":
            games = _get_json(QUILT_GAMES)
            ok = any((x.get("version") or x.get("id")) == version for x in games)
        elif loader == "Paper":
            versions = _get_json(PAPER_PROJECT).get("versions", [])
            ok = version in versions
        elif loader == "Purpur":
            versions = _get_json(PURPUR_PROJECT).get("versions", [])
            ok = version in versions
        elif loader == "Forge":
            versions = _xml_versions(FORGE_META)
            ok = any(v.startswith(version + "-") for v in versions)
        elif loader == "NeoForge":
            versions = _xml_versions(NEOFORGE_META)
            compact = version[2:] if version.startswith("1.") else version
            ok = any(v.startswith(compact + ".") or v.startswith(version + ".") for v in versions)
        else:
            return "ℹ️ Compatibility is not known for this target."
        if ok:
            return f"✅ **{loader}** currently publishes metadata compatible with **Minecraft {version}**."
        return (
            f"⚠️ I could not confirm a published **{loader}** build for **Minecraft {version}**. "
            "BlockSmith can still generate a port/scaffold, but it may not compile until that loader supports the version."
        )
    except Exception as exc:
        return f"ℹ️ Live {loader} compatibility check is temporarily unavailable: `{type(exc).__name__}`."


def _safe_relpath(name: str) -> Optional[str]:
    name = name.replace("\\", "/").lstrip("/")
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts:
        return None
    if len(p.parts) > 20:
        return None
    return str(p)


def _read_text(raw: bytes) -> Optional[str]:
    if len(raw) > MAX_SINGLE_TEXT:
        raw = raw[:MAX_SINGLE_TEXT]
    if b"\x00" in raw[:4096]:
        return None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return None


def _summarize_zip(path: Path) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    notes: list[str] = []
    used = 0
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if sum(i.file_size for i in infos) > 250_000_000:
                notes.append("Archive is larger than 250 MB uncompressed; only a bounded source sample was read.")
            for info in infos:
                if len(entries) >= MAX_IMPORT_FILES or used >= MAX_IMPORT_BYTES:
                    break
                rel = _safe_relpath(info.filename)
                if not rel or info.is_dir() or info.file_size > MAX_SINGLE_TEXT:
                    continue
                suffix = Path(rel).suffix.lower()
                if suffix not in ALLOWED_TEXT_SUFFIXES and Path(rel).name not in RISKY_BUILD_NAMES:
                    continue
                try:
                    raw = zf.read(info)
                except Exception:
                    continue
                text = _read_text(raw)
                if text is None:
                    continue
                used += len(raw)
                entries.append({"path": rel, "content": text})
            if path.suffix.lower() == ".jar":
                notes.append(
                    "Compiled .class bytecode was not decompiled. Text resources/metadata were imported; "
                    "for deep code edits upload a source JAR or source project ZIP."
                )
    except zipfile.BadZipFile:
        notes.append("The uploaded archive is not a readable ZIP/JAR.")
    return entries, notes


def _summarize_folder(paths: Optional[Iterable[str]]) -> tuple[list[dict], list[str]]:
    if not paths:
        return [], []
    entries: list[dict] = []
    used = 0
    for item in list(paths)[:MAX_IMPORT_FILES]:
        p = Path(item)
        if not p.is_file() or p.stat().st_size > MAX_SINGLE_TEXT:
            continue
        if p.suffix.lower() not in ALLOWED_TEXT_SUFFIXES and p.name not in RISKY_BUILD_NAMES:
            continue
        raw = p.read_bytes()
        text = _read_text(raw)
        if text is None:
            continue
        used += len(raw)
        if used > MAX_IMPORT_BYTES:
            break
        entries.append({"path": p.name, "content": text})
    return entries, []


def inspect_base(base_archive, base_folder) -> tuple[list[dict], list[str]]:
    if base_archive:
        path = Path(base_archive)
        return _summarize_zip(path)
    return _summarize_folder(base_folder)


SYSTEM_PROMPT = r"""
You are BlockSmith, a senior Minecraft Java mod/plugin/resource-pack/shader engineer.
Return ONE strict JSON object and nothing else.

Your job is to generate a complete editable project for the exact artifact, loader/platform,
and Minecraft version requested. The project should be practical, minimal, well-structured,
and ready for a developer to build locally.

Required JSON schema:
{
  "summary": "short human-readable summary",
  "warnings": ["zero or more concise warnings"],
  "files": [
    {"path": "relative/path.ext", "content": "full UTF-8 file content"}
  ]
}

Rules:
- Never use absolute paths or ../ paths.
- For Java/Kotlin mods/plugins, include the normal build files and loader metadata a real project needs.
- For Fabric use fabric.mod.json; Forge/NeoForge use the metadata expected by that platform/version;
  Quilt uses quilt.mod.json; Paper/Purpur plugins include plugin.yml or paper-plugin.yml as appropriate.
- Resource packs must contain pack.mcmeta and assets/...; shader packs should use a conventional shaders/ layout.
- If a Minecraft snapshot is selected, target that exact snapshot where the loader supports it; otherwise clearly warn.
- If an existing project was supplied, preserve its intent and improve/port it rather than replacing unrelated pieces.
- Do not add binaries as base64. Text/source files only.
- Do not include secrets, access tokens, telemetry, miners, remote-control code, or self-updaters.
- Do not fetch or execute code at runtime.
- Keep build scripts ordinary and transparent.
- Make IDs/namespaces lowercase and filesystem-safe.
"""


def _prompt_payload(
    project_name: str,
    artifact_kind: str,
    loader: str,
    minecraft_version: str,
    user_prompt: str,
    imported_files: list[dict],
    import_notes: list[str],
    include_readme: bool,
) -> str:
    base = {
        "project_name": project_name,
        "artifact_kind": artifact_kind,
        "loader": loader,
        "minecraft_version": minecraft_version,
        "request": user_prompt,
        "include_readme": include_readme,
        "import_notes": import_notes,
        "existing_files": imported_files,
    }
    return (
        "Build this Minecraft project. Respect the exact target and return the required JSON.\n"
        + json.dumps(base, ensure_ascii=False)
    )


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
            return json.loads(text[first:last + 1])
        raise


def _sanitize_files(raw_files) -> tuple[list[dict], list[str]]:
    safe: list[dict] = []
    warnings: list[str] = []
    seen = set()
    total = 0
    if not isinstance(raw_files, list):
        raise ValueError("Model output did not contain a files list.")
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        rel = _safe_relpath(str(item.get("path", "")))
        content = item.get("content")
        if not rel or not isinstance(content, str):
            warnings.append("Dropped an invalid generated file entry.")
            continue
        if rel in seen:
            warnings.append(f"Dropped duplicate file: {rel}")
            continue
        if len(content.encode("utf-8")) > 800_000:
            warnings.append(f"Dropped oversized text file: {rel}")
            continue
        total += len(content.encode("utf-8"))
        if total > 12_000_000:
            warnings.append("Output exceeded the 12 MB text-project limit; remaining files were dropped.")
            break
        seen.add(rel)
        safe.append({"path": rel, "content": content})
    if not safe:
        raise ValueError("Kimi returned no usable project files.")
    return safe, warnings


def _required_file_warnings(artifact_kind: str, loader: str, paths: set[str]) -> list[str]:
    low = {p.lower() for p in paths}
    out = []
    if artifact_kind == "Resource pack" and "pack.mcmeta" not in low:
        out.append("Generated resource pack is missing pack.mcmeta.")
    if artifact_kind == "Shader pack" and not any(p.startswith("shaders/") for p in low):
        out.append("Generated shader pack has no shaders/ directory.")
    if loader == "Fabric" and not any(p.endswith("fabric.mod.json") for p in low):
        out.append("Fabric project is missing fabric.mod.json.")
    if loader == "Quilt" and not any(p.endswith("quilt.mod.json") for p in low):
        out.append("Quilt project is missing quilt.mod.json.")
    if loader in {"Paper", "Purpur"} and not any(
        p.endswith("plugin.yml") or p.endswith("paper-plugin.yml") for p in low
    ):
        out.append(f"{loader} plugin is missing plugin.yml/paper-plugin.yml.")
    return out


def _write_zip(project_name: str, files: list[dict], include_readme: bool, status_text: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "minecraft-project"
    out_dir = Path(tempfile.mkdtemp(prefix="blocksmith-out-"))
    out_path = out_dir / f"{safe_name}.zip"
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as zf:
        for item in files:
            zf.writestr(item["path"], item["content"])
        if include_readme and not any(Path(x["path"]).name.lower() == "readme.md" for x in files):
            zf.writestr(
                "README.md",
                "# Generated by BlockSmith\n\n"
                + status_text
                + "\n\nThis archive was generated by Kimi K3 through Hugging Face. "
                  "Review generated code before building or publishing it.\n",
            )
        zf.writestr(
            "BLOCKSMITH_BUILD_INFO.txt",
            status_text
            + "\n\nSecurity note: the Space packages generated source but does not execute "
              "AI-written build scripts on the server. Build Java projects locally or in your own CI.\n",
        )
    return str(out_path)


def build_project(
    *,
    project_name: str,
    artifact_kind: str,
    loader: str,
    minecraft_version: str,
    user_prompt: str,
    base_archive,
    base_folder,
    include_readme: bool,
    hf_token: str,
):
    if not user_prompt or len(user_prompt.strip()) < 8:
        raise ValueError("Describe what you want the project to do.")
    project_name = (project_name or "MinecraftProject").strip()[:80]
    imported, import_notes = inspect_base(base_archive, base_folder)

    client = InferenceClient(provider="auto", api_key=hf_token, timeout=180)
    response = client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _prompt_payload(
                    project_name,
                    artifact_kind,
                    loader,
                    minecraft_version,
                    user_prompt,
                    imported,
                    import_notes,
                    include_readme,
                ),
            },
        ],
        max_tokens=20000,
        temperature=0.2,
    )
    text = response.choices[0].message.content
    parsed = _extract_json(text)
    files, sanitize_warnings = _sanitize_files(parsed.get("files"))
    paths = {x["path"] for x in files}

    warnings = []
    warnings.extend(import_notes)
    warnings.extend(parsed.get("warnings") or [])
    warnings.extend(sanitize_warnings)
    warnings.extend(_required_file_warnings(artifact_kind, loader, paths))

    summary = str(parsed.get("summary") or f"Generated {project_name}.")
    direct_use = artifact_kind in {"Resource pack", "Shader pack"}
    build_kind = "directly usable pack ZIP" if direct_use else "source-project ZIP"
    status_lines = [
        f"Generated **{len(files)} files** for **Minecraft {minecraft_version} / {loader}** using **{KIMI_MODEL}**.",
        f"Output type: **{build_kind}**.",
    ]
    if imported:
        status_lines.append(f"Used **{len(imported)} editable files** from the uploaded base as context.")
    if not direct_use:
        status_lines.append(
            "For safety, the public Space does **not execute AI-written Gradle/Maven/shell scripts**. "
            "The ZIP contains the build files Kimi generated so you can build it locally or in your own CI."
        )
    if warnings:
        status_lines.append("\n**Warnings:**\n" + "\n".join(f"- {w}" for w in warnings[:12]))

    status = "\n\n".join(status_lines)
    out_path = _write_zip(project_name, files, include_readme, status.replace("**", ""))

    manifest = {
        "model": KIMI_MODEL,
        "minecraft_version": minecraft_version,
        "loader": loader,
        "artifact_kind": artifact_kind,
        "summary": summary,
        "file_count": len(files),
        "files": [x["path"] for x in files],
        "warnings": warnings,
        "imported_editable_files": len(imported),
    }
    return status, out_path, manifest
