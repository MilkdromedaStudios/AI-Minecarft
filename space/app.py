from __future__ import annotations

import os
import traceback
from pathlib import Path

import gradio as gr
import spaces

import minecraft_builder as minecraft_builder_module
import modeling_builder as modeling_builder_module
from minecraft_builder import KIMI_MODEL, BlockSmithError, build_project, list_minecraft_versions, loader_note
from modeling_builder import MODEL_FORMATS, build_model_project

SPACE_HOST = (os.getenv("SPACE_HOST") or "respawnerzstudioz-blocksmith-minecraft.hf.space").strip()
SPACE_BASE_URL = f"https://{SPACE_HOST}"
HF_LOGIN_URL = f"{SPACE_BASE_URL}/login/huggingface"
HF_LOGOUT_URL = f"{SPACE_BASE_URL}/logout"
HF_BILLING_URL = "https://huggingface.co/settings/billing"
HF_INFERENCE_SETTINGS_URL = "https://huggingface.co/settings/inference-providers"
KIMI_PRIMARY_MODEL = KIMI_MODEL
KIMI_FALLBACK_MODEL = "moonshotai/Kimi-K2.7-Code"

THEME = gr.themes.Soft().set(
    body_background_fill="#f7f8fb",
    body_background_fill_dark="#090d15",
    body_text_color="#172033",
    body_text_color_dark="#f8fafc",
    block_background_fill="#ffffff",
    block_background_fill_dark="#111827",
    block_border_color="#d8dee9",
    block_border_color_dark="#263244",
    input_background_fill="#ffffff",
    input_background_fill_dark="#172033",
)

CSS = r"""
.gradio-container {
  max-width: 1500px !important;
  width: 100% !important;
  overflow-x: hidden !important;
}
#hero, .mc-card {
  border: 1px solid var(--block-border-color);
  background: var(--block-background-fill);
  box-shadow: 0 14px 40px rgba(15,23,42,.08);
  border-radius: 18px;
}
#hero { padding: 22px 26px; margin-bottom: 14px; }
#hero h1 { margin: 0; font-size: clamp(28px,4vw,46px); }
#hero p { color: var(--body-text-color-subdued); font-size: 16px; }
.mc-badge {
  display:inline-block; padding:5px 10px; margin:3px;
  border-radius:999px; border:1px solid var(--block-border-color);
  background:var(--background-fill-secondary); font-size:12px;
}
#top-controls { gap: 8px; }
#theme-button button, #build-btn button {
  min-height: 44px !important;
  touch-action: manipulation;
}
#theme-button button { width: 100% !important; }
#build-btn button { font-weight: 750; }
#auth-status { font-size: 13px; }
.oauth-direct-link {
  display:flex;
  align-items:center;
  justify-content:center;
  width:100%;
  min-height:46px;
  padding:10px 14px;
  border-radius:10px;
  box-sizing:border-box;
  text-decoration:none !important;
  font-weight:700;
  text-align:center;
  touch-action:manipulation;
  -webkit-tap-highlight-color:transparent;
}
.oauth-signin {
  background:#FFD21E;
  color:#111827 !important;
  border:1px solid #e1b900;
}
.oauth-signout {
  background:var(--button-secondary-background-fill);
  color:var(--body-text-color) !important;
  border:1px solid var(--block-border-color);
}
footer { visibility:hidden; }

@media (max-width: 780px) {
  .gradio-container {
    padding: 8px !important;
    margin: 0 !important;
  }
  #top-row, #workspace-row {
    flex-direction: column !important;
    gap: 10px !important;
  }
  #top-row > *, #workspace-row > * {
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    flex: 1 1 auto !important;
  }
  #top-controls {
    width: 100% !important;
    min-width: 0 !important;
  }
  #hero {
    padding: 16px 14px !important;
    margin-bottom: 4px !important;
  }
  #hero h1 { font-size: 30px !important; }
  #hero p { font-size: 14px !important; }
  .mc-badge { font-size: 11px; padding: 4px 8px; margin: 2px; }
  input, textarea, select { font-size: 16px !important; }
  button, .oauth-direct-link { min-height: 48px !important; }
}
"""

INIT_JS = r"""
() => {
  const url = new URL(window.location.href);
  const saved = localStorage.getItem('blocksmith-theme');
  const systemDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const desired = saved || (systemDark ? 'dark' : 'light');
  if (url.searchParams.get('__theme') !== desired) {
    url.searchParams.set('__theme', desired);
    window.location.replace(url.toString());
  }
}
"""

TOGGLE_JS = r"""
() => {
  const url = new URL(window.location.href);
  const current = url.searchParams.get('__theme') ||
    (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = current === 'dark' ? 'light' : 'dark';
  localStorage.setItem('blocksmith-theme', next);
  url.searchParams.set('__theme', next);
  window.location.assign(url.toString());
  return [];
}
"""

ARTIFACTS = ["Minecraft mod", "Server plugin", "Resource pack", "Shader pack", "3D model / animation"]
OUTPUT_CHOICES = ["JAR + Source", "JAR only", "Source only"]


@spaces.GPU(duration=1)
def _zerogpu_marker() -> str:
    """ZeroGPU registration marker; normal BlockSmith requests never call this."""
    return "BlockSmith uses remote Hugging Face Inference Providers."


def refresh_versions():
    versions = list_minecraft_versions()
    default = versions[0] if versions else "latest"
    return gr.update(choices=versions, value=default), f"Loaded **{len(versions)}** Mojang Java versions, including releases and snapshots."


def bootstrap_auth(
    profile: gr.OAuthProfile | None,
    oauth_token: gr.OAuthToken | None,
):
    """Resolve OAuth once per page load and keep only the visitor token in server-side session state."""
    if profile is None or oauth_token is None or not getattr(oauth_token, "token", None):
        print("[BlockSmith auth] no usable OAuth token in this session", flush=True)
        return (
            "🔐 **Sign-in needed once.** Tap the yellow button below, authorize BlockSmith, then return to the app.",
            gr.update(visible=True),
            gr.update(visible=False),
            None,
        )
    name = getattr(profile, "name", None) or "Hugging Face user"
    print(f"[BlockSmith auth] authenticated user={name!r}; visitor token loaded into session state", flush=True)
    return (
        f"✅ **Signed in as {name}.** Builds use your own Hugging Face inference allowance—not the Space owner's token.",
        gr.update(visible=False),
        gr.update(visible=True),
        oauth_token.token,
    )


def on_artifact_change(kind: str):
    if kind == "Minecraft mod":
        return (
            gr.update(label="Loader / platform", choices=["Fabric", "Forge", "NeoForge", "Quilt"], value="Fabric"),
            gr.update(visible=True, value="JAR + Source"),
            gr.update(visible=False, value=None),
        )
    if kind == "Server plugin":
        return (
            gr.update(label="Loader / platform", choices=["Paper", "Purpur"], value="Paper"),
            gr.update(visible=True, value="JAR + Source"),
            gr.update(visible=False, value=None),
        )
    if kind == "3D model / animation":
        return (
            gr.update(label="Model format / target", choices=MODEL_FORMATS, value=MODEL_FORMATS[0]),
            gr.update(visible=False, value="Source only"),
            gr.update(visible=True, value=None),
        )
    return (
        gr.update(label="Loader / platform", choices=["Vanilla / N/A"], value="Vanilla / N/A"),
        gr.update(visible=False, value="Source only"),
        gr.update(visible=False, value=None),
    )


def explain_loader(loader: str, version: str):
    if loader in MODEL_FORMATS:
        notes = {
            "Java block/item model": "🧊 Generates Minecraft Java block/item model JSON, elements, faces, UVs, and texture references.",
            "Blockbench (.bbmodel)": "📐 Generates an editable Blockbench `.bbmodel` project plus a practical runtime export when appropriate.",
            "GeckoLib model + animation": "🦎 Generates GeckoLib geometry and animation JSON with matching bones, pivots, cubes, UVs, and animation channels.",
            "Modded entity model": "🧍 Generates entity geometry/model assets and the small model/renderer source needed to use them in a mod.",
        }
        return notes.get(loader, "3D modeling target.")
    return loader_note(loader, version)


def _normalize_builder_result(result):
    """Validate a builder result before Gradio post-processes it."""
    if not isinstance(result, (tuple, list)) or len(result) != 4:
        raise BlockSmithError(f"Builder returned an invalid result shape: {type(result).__name__}")
    status, outputs, manifest, log = result
    if outputs is None:
        outputs = []
    if not isinstance(outputs, (list, tuple)):
        outputs = [outputs]

    safe_outputs: list[str] = []
    output_notes: list[str] = []
    for value in outputs:
        if value in (None, ""):
            continue
        path = Path(str(value)).expanduser()
        if not path.is_file():
            output_notes.append(f"Generated output path does not exist: {path}")
            continue
        safe_outputs.append(str(path.resolve()))

    log_text = str(log or "")
    if output_notes:
        note = "\n".join(output_notes)
        log_text += "\n\n=== Output verification ===\n" + note
        status = str(status or "") + "\n\n⚠️ **Output verification issue:** one or more generated download files were missing. See the log below."

    if not isinstance(manifest, (dict, list, str)) and manifest is not None:
        manifest = {"ok": False, "warning": f"Non-JSON manifest converted from {type(manifest).__name__}", "value": str(manifest)}

    return str(status or ""), safe_outputs, manifest or {}, log_text


def _set_runtime_kimi_model(model: str) -> None:
    """Set the model used by both builders. Queue concurrency is one, so this is request-safe."""
    minecraft_builder_module.KIMI_MODEL = model
    modeling_builder_module.KIMI_MODEL = model


def _is_provider_routing_failure(message: str) -> bool:
    """Only fall back for provider/model availability problems, never auth, billing, or rate limits."""
    low = message.lower()
    if not ("inference failed" in low or "inference" in low and "provider" in low):
        return False
    user_account_failures = (
        "401", "402", "403", "429", "unauthor", "forbidden", "payment", "credit", "rate limit", "quota"
    )
    return not any(marker in low for marker in user_account_failures)


def _classify_failure(message: str) -> tuple[str, str, str, str]:
    """Turn provider/framework wording into an actionable user-facing error category."""
    low = (message or "").lower()

    if "402" in low or "payment required" in low or any(
        phrase in low
        for phrase in (
            "credits may be exhausted",
            "credit balance",
            "insufficient credit",
            "insufficient balance",
            "out of credit",
            "out of credits",
            "no credits",
            "purchase credits",
        )
    ):
        return (
            "hf_inference_credits_exhausted",
            "💳 Out of Hugging Face inference credits",
            "The signed-in Hugging Face account does not have enough Inference Providers credit for this request. BlockSmith did not use the Space owner's deployment token.",
            f"Add/purchase Hugging Face inference credits or wait for the account's monthly allowance to reset. Billing: {HF_BILLING_URL}",
        )

    if "429" in low or "rate limit" in low or "too many requests" in low:
        return (
            "hf_inference_rate_limited",
            "⏳ Hugging Face inference is rate-limited",
            "The signed-in Hugging Face account or selected provider is temporarily rate-limited.",
            "Try again later. Repeated retries immediately may continue to be rejected.",
        )

    if any(marker in low for marker in ("401", "403", "unauthor", "forbidden", "invalid token", "expired token")):
        return (
            "hf_oauth_not_authorized",
            "🔐 Hugging Face authorization problem",
            "BlockSmith could not use the signed-in visitor's OAuth token for inference.",
            "Sign out of BlockSmith, sign in again, and approve inference access.",
        )

    if any(marker in low for marker in ("timeout", "timed out", "read timeout", "connect timeout")):
        return (
            "inference_timeout",
            "⌛ Inference request timed out",
            "The model/provider did not finish the request before the request timeout.",
            "Try again, or use a smaller request/import if the project is very large.",
        )

    if _is_provider_routing_failure(message) or any(
        marker in low for marker in ("no provider", "provider unavailable", "model is not supported", "not supported by any provider")
    ):
        return (
            "hf_provider_unavailable",
            "🛰️ No Hugging Face provider route is available",
            "Hugging Face could not route the selected Kimi model to an inference provider for this request.",
            f"Check Hugging Face Inference Providers settings or try again later: {HF_INFERENCE_SETTINGS_URL}",
        )

    if "not valid project json" in low or "not valid project" in low or "no usable" in low:
        return (
            "model_output_invalid",
            "🧩 Kimi returned invalid project output",
            "The model answered, but its generated project data could not be parsed or safely packaged.",
            "Try the request again. BlockSmith's log below contains the exact parser/validation message.",
        )

    return (
        "blocksmith_failure",
        "❌ BlockSmith could not complete the request",
        "BlockSmith stopped because one of the generation, validation, compilation, or provider steps failed.",
        "Read the exact technical message and log below; they are preserved instead of being replaced with a generic Error popup.",
    )


def _friendly_error_result(
    message: str,
    *,
    error_type: str,
    failures: list[str] | None = None,
    traceback_text: str | None = None,
):
    code, title, explanation, action = _classify_failure(message)
    safe_message = (message or "Unknown error").strip().replace("`", "'")
    if len(safe_message) > 1800:
        safe_message = safe_message[:1800] + "…"

    log_lines = [
        f"Error category: {code}",
        f"Error type: {error_type}",
        f"Raw error: {message}",
    ]
    if failures:
        log_lines.append("\n=== Model attempts ===\n" + "\n".join(failures))
    if traceback_text:
        log_lines.append("\n=== Python traceback ===\n" + traceback_text)

    return (
        f"## {title}\n\n{explanation}\n\n**What to do:** {action}\n\n**Technical message:** `{safe_message}`\n\nThis request used only the signed-in visitor's Hugging Face OAuth token.",
        [],
        {
            "ok": False,
            "error_code": code,
            "error_type": error_type,
            "message": message,
            "model_attempts": failures or [],
            "visitor_oauth": True,
        },
        "\n".join(log_lines),
    )


def _execute_builder(
    *,
    project_name: str,
    artifact_kind: str,
    loader: str,
    version: str,
    prompt: str,
    output_preference: str,
    reference_image,
    base_archive,
    base_folder,
    include_readme: bool,
    token: str,
):
    if artifact_kind == "3D model / animation":
        return build_model_project(
            project_name=project_name,
            model_format=loader,
            minecraft_version=version,
            user_prompt=prompt,
            reference_image=reference_image,
            hf_token=token,
        )
    return build_project(
        project_name=project_name,
        artifact_kind=artifact_kind,
        loader=loader,
        minecraft_version=version,
        user_prompt=prompt,
        base_archive=base_archive,
        base_folder=base_folder,
        include_readme=include_readme,
        hf_token=token,
        output_preference=output_preference,
    )


def run_builder(
    project_name: str,
    artifact_kind: str,
    loader: str,
    version: str,
    prompt: str,
    output_preference: str,
    reference_image,
    base_archive,
    base_folder,
    include_readme: bool,
    hf_token: str | None,
):
    """Run one BlockSmith build using only the signed-in visitor's OAuth token."""
    token = hf_token if isinstance(hf_token, str) and hf_token.strip() else None
    print(
        f"[BlockSmith build] start artifact={artifact_kind!r} loader={loader!r} version={version!r} auth={'yes' if token else 'no'}",
        flush=True,
    )
    if not token:
        return (
            "## 🔐 Sign-in required\n\nBlockSmith does not have a visitor OAuth token for this browser session. Sign in with Hugging Face and retry.\n\n**No Space-owner API key will be used as a fallback.**",
            [],
            {"ok": False, "error_code": "missing_hf_oauth_session_state", "visitor_oauth": False},
            "Build stopped before inference because the visitor OAuth session token was empty.",
        )

    failures: list[str] = []
    models = [KIMI_PRIMARY_MODEL, KIMI_FALLBACK_MODEL]
    try:
        for index, model in enumerate(models):
            _set_runtime_kimi_model(model)
            print(f"[BlockSmith build] inference model attempt={index + 1} model={model}", flush=True)
            try:
                result = _execute_builder(
                    project_name=project_name,
                    artifact_kind=artifact_kind,
                    loader=loader,
                    version=version,
                    prompt=prompt,
                    output_preference=output_preference,
                    reference_image=reference_image,
                    base_archive=base_archive,
                    base_folder=base_folder,
                    include_readme=include_readme,
                    token=token,
                )
                normalized = _normalize_builder_result(result)
                status, output_files, manifest, log = normalized
                if isinstance(manifest, dict):
                    manifest["model_used"] = model
                    manifest["visitor_oauth"] = True
                    manifest["fallback_used"] = model != KIMI_PRIMARY_MODEL
                if model != KIMI_PRIMARY_MODEL:
                    status = (
                        f"ℹ️ **{KIMI_PRIMARY_MODEL} could not be routed through Hugging Face for this request, so BlockSmith automatically used {model} with your same visitor OAuth token.**\n\n"
                        + status
                    )
                    log = "\n".join(failures + [f"Fallback model succeeded: {model}", log])
                print(f"[BlockSmith build] completed model={model} outputs={len(output_files)}", flush=True)
                return status, output_files, manifest, log
            except BlockSmithError as exc:
                message = str(exc)
                failures.append(f"Model attempt failed ({model}): {type(exc).__name__}: {message}")
                print(f"[BlockSmith build] model failure model={model}: {message}", flush=True)
                if index == 0 and _is_provider_routing_failure(message):
                    continue
                raise

        raise BlockSmithError("No Kimi inference route completed successfully.\n" + "\n".join(failures))
    except BlockSmithError as exc:
        message = str(exc)
        print(f"[BlockSmith build] handled failure: {type(exc).__name__}: {message}", flush=True)
        return _friendly_error_result(message, error_type=type(exc).__name__, failures=failures)
    except Exception as exc:
        tb = traceback.format_exc(limit=20)
        message = str(exc).strip() or repr(exc)
        print("[BlockSmith build] unexpected exception\n" + tb, flush=True)
        return _friendly_error_result(
            message,
            error_type=type(exc).__name__,
            failures=failures,
            traceback_text=tb,
        )
    finally:
        _set_runtime_kimi_model(KIMI_PRIMARY_MODEL)


with gr.Blocks(title="BlockSmith — Kimi Minecraft Builder", theme=THEME) as demo:
    # Sensitive OAuth data stays in per-session server state, never BrowserState/localStorage.
    oauth_session_token = gr.State(value=None, time_to_live=60 * 60 * 12)

    with gr.Row(elem_id="top-row"):
        gr.HTML(
            f"""
            <section id="hero">
              <h1>⛏️ BlockSmith</h1>
              <p>Generate, model, compile, repair, and validate Minecraft projects with <b>{KIMI_PRIMARY_MODEL}</b>, with an automatic Kimi coding fallback if HF routing is unavailable.</p>
              <div>
                <span class="mc-badge">Fabric</span><span class="mc-badge">Forge</span>
                <span class="mc-badge">NeoForge</span><span class="mc-badge">Quilt</span>
                <span class="mc-badge">Paper</span><span class="mc-badge">Purpur</span>
                <span class="mc-badge">Blockbench</span><span class="mc-badge">GeckoLib</span>
                <span class="mc-badge">Reference images</span>
                <span class="mc-badge">Releases + snapshots</span>
                <span class="mc-badge">Auto repair</span><span class="mc-badge">Shader validation</span>
              </div>
            </section>
            """,
            scale=8,
        )
        with gr.Column(scale=1, min_width=150, elem_id="top-controls"):
            auth_status = gr.Markdown("Checking Hugging Face sign-in…", elem_id="auth-status")

            # Hidden LoginButton registers Gradio's Hugging Face OAuth routes.
            gr.LoginButton(visible=False)
            sign_in_link = gr.HTML(
                f'<a class="oauth-direct-link oauth-signin" href="{HF_LOGIN_URL}" target="_top">🤗 Sign in to use your own HF inference</a>',
                visible=True,
            )
            sign_out_link = gr.HTML(
                f'<a class="oauth-direct-link oauth-signout" href="{HF_LOGOUT_URL}" target="_top">Sign out of BlockSmith</a>',
                visible=False,
            )
            theme_btn = gr.Button("🌓 Light / Dark", elem_id="theme-button", size="md")

    with gr.Row(elem_id="workspace-row"):
        with gr.Column(scale=3, elem_classes="mc-card"):
            gr.Markdown("### 1. Choose the target")
            with gr.Row():
                project_name = gr.Textbox(label="Project name", value="MyAwesomeProject", placeholder="e.g. BetterCaves", scale=2)
                artifact_kind = gr.Dropdown(ARTIFACTS, value="Minecraft mod", label="What are you making?", scale=2)
            with gr.Row():
                loader = gr.Dropdown(["Fabric", "Forge", "NeoForge", "Quilt"], value="Fabric", label="Loader / platform")
                version = gr.Dropdown(["latest"], value="latest", allow_custom_value=True, label="Minecraft version", info="Live Mojang list, including snapshots.")
            refresh = gr.Button("↻ Refresh Minecraft versions", size="sm")
            version_status = gr.Markdown("Version list loads when the app opens.")
            compatibility = gr.Markdown()

            output_preference = gr.Radio(
                OUTPUT_CHOICES,
                value="JAR + Source",
                label="Java project output",
                info="BlockSmith compiles with trusted build scaffolding, then feeds compiler errors back to Kimi for up to 3 repair attempts.",
            )

            reference_image = gr.Image(
                label="Optional reference image for 3D modeling",
                type="filepath",
                visible=False,
                sources=["upload", "clipboard"],
            )
            gr.Markdown(
                "Kimi can inspect the uploaded reference image and use it to reconstruct Minecraft geometry, UVs, animation structure, and small pixel textures."
            )

            gr.Markdown("### 2. Describe what you want")
            prompt = gr.Textbox(
                label="Build / modeling instructions",
                lines=9,
                placeholder="Example: Make a Fabric mod with a grappling hook — or choose 3D model and make a low-poly crystal golem with articulated arms and a 32x32 texture.",
            )

            gr.Markdown("### 3. Optional: improve an existing project")
            with gr.Tabs():
                with gr.Tab("ZIP / JAR / pack"):
                    base_archive = gr.File(label="Upload ZIP, JAR, resource pack, shader pack, or source archive", file_count="single", type="filepath")
                with gr.Tab("Folder"):
                    base_folder = gr.File(label="Upload a project folder", file_count="directory", type="filepath")
            include_readme = gr.Checkbox(value=True, label="Include README + build/use instructions")
            build_btn = gr.Button("✨ Make → Build / Model → Repair → Verify", variant="primary", elem_id="build-btn")

        with gr.Column(scale=2, elem_classes="mc-card"):
            gr.Markdown("### Result")
            status = gr.Markdown("BlockSmith will show the exact reason when generation, billing, authorization, routing, compilation, or validation fails.")
            output_files = gr.File(label="Download JAR / source / model / pack", file_count="multiple")
            manifest = gr.JSON(label="Build manifest")
            build_log = gr.Textbox(label="Build / validation log", lines=18, max_lines=40, interactive=False, show_copy_button=True)
            gr.Markdown(
                """
                **Verification levels**
                - **Mods/plugins:** compiles using BlockSmith-owned build scaffolding; compiler errors are sent back to Kimi for repair, up to 3 attempts.
                - **3D models:** validates Java model JSON / `.bbmodel` / GeckoLib geometry and animations, UV/geometry structure, generated PNG texture grids, and obvious broken references. A reference image can guide the model.
                - **Shaders:** checks layout/includes and runs GLSL syntax validation when possible, then repairs validator failures.
                - **Resource packs:** validates `pack.mcmeta` and basic structure.

                Model/shader validation is structural. Final appearance still needs an artistic check in Blockbench or Minecraft.
                """
            )

    theme_btn.click(fn=None, js=TOGGLE_JS)
    artifact_kind.change(on_artifact_change, inputs=artifact_kind, outputs=[loader, output_preference, reference_image])
    loader.change(explain_loader, inputs=[loader, version], outputs=compatibility)
    version.change(explain_loader, inputs=[loader, version], outputs=compatibility)
    refresh.click(refresh_versions, outputs=[version, version_status], api_name="refresh_versions")
    demo.load(refresh_versions, outputs=[version, version_status])
    demo.load(
        bootstrap_auth,
        inputs=None,
        outputs=[auth_status, sign_in_link, sign_out_link, oauth_session_token],
    )
    build_btn.click(
        run_builder,
        inputs=[
            project_name,
            artifact_kind,
            loader,
            version,
            prompt,
            output_preference,
            reference_image,
            base_archive,
            base_folder,
            include_readme,
            oauth_session_token,
        ],
        outputs=[status, output_files, manifest, build_log],
        api_name="build",
        concurrency_limit=1,
    )

if __name__ == "__main__":
    # BlockSmith renders its own full diagnostics; suppress Gradio's generic red "Error" overlay.
    demo.queue(default_concurrency_limit=1).launch(css=CSS, js=INIT_JS, show_error=False)
