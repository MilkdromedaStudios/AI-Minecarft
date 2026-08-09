from __future__ import annotations

import os
import traceback
from typing import Optional

import gradio as gr
import spaces

from minecraft_builder import KIMI_MODEL, BlockSmithError, build_project, list_minecraft_versions, loader_note
from modeling_builder import MODEL_FORMATS, build_model_project

SPACE_HOST = (os.getenv("SPACE_HOST") or "respawnerzstudioz-blocksmith-minecraft.hf.space").strip()
SPACE_BASE_URL = f"https://{SPACE_HOST}"
HF_LOGIN_URL = f"{SPACE_BASE_URL}/login/huggingface"
HF_LOGOUT_URL = f"{SPACE_BASE_URL}/logout"

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


def auth_state(profile: Optional[gr.OAuthProfile]):
    if profile is None:
        return (
            "🔐 **Sign-in needed once.** Tap the yellow button below. It opens BlockSmith directly, outside the Hugging Face iframe, so OAuth works reliably on mobile.",
            gr.update(visible=True),
            gr.update(visible=False),
        )
    name = getattr(profile, "name", None) or "Hugging Face user"
    return (
        f"✅ **Signed in as {name}.** Your authorized Hugging Face session is active.",
        gr.update(visible=False),
        gr.update(visible=True),
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
    oauth_token: Optional[gr.OAuthToken],
):
    token = oauth_token.token if oauth_token else None
    if not token:
        return (
            "## ❌ Sign-in required\n\nBlockSmith could not detect an authorized Hugging Face session. Use the yellow **Sign in with Hugging Face** link once, approve inference access, then retry.",
            [],
            {"ok": False, "error": "missing_hf_oauth_token"},
            "No Hugging Face OAuth token was supplied to the build function.",
        )
    try:
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
    except BlockSmithError as exc:
        message = str(exc)
        return (
            f"## ❌ Build failed\n\n**{message}**\n\nThe full diagnostic message is shown in **Build / validation log** below. No silent `Error` popup should be needed.",
            [],
            {"ok": False, "error_type": type(exc).__name__, "message": message},
            f"{type(exc).__name__}: {message}",
        )
    except Exception as exc:
        tb = traceback.format_exc(limit=12)
        return (
            f"## ❌ Unexpected BlockSmith error\n\n**{type(exc).__name__}: {exc}**\n\nA traceback is available in the log below so this failure can be debugged instead of appearing as an unexplained `Error`.",
            [],
            {"ok": False, "error_type": type(exc).__name__, "message": str(exc)},
            tb,
        )


with gr.Blocks(title="BlockSmith — Kimi K3 Minecraft Builder", theme=THEME) as demo:
    with gr.Row(elem_id="top-row"):
        gr.HTML(
            f"""
            <section id="hero">
              <h1>⛏️ BlockSmith</h1>
              <p>Generate, model, compile, repair, and validate Minecraft projects with <b>{KIMI_MODEL}</b>.</p>
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

            # Keep a hidden LoginButton so Gradio registers /login/huggingface,
            # /login/callback, and /logout. The visible controls below use native
            # top-level links to avoid iframe/mobile click and popup issues.
            gr.LoginButton(visible=False)
            sign_in_link = gr.HTML(
                f'<a class="oauth-direct-link oauth-signin" href="{HF_LOGIN_URL}" target="_top">🤗 Sign in with Hugging Face</a>',
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
                info="Kimi K3 can inspect the image and reconstruct recognizable Minecraft geometry, UVs, animation structure, and small pixel textures.",
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
            build_btn = gr.Button("✨ Generate → Build / Model → Repair → Verify", variant="primary", elem_id="build-btn")

        with gr.Column(scale=2, elem_classes="mc-card"):
            gr.Markdown("### Result")
            status = gr.Markdown("BlockSmith will show generation, compilation/modeling, repair, and validation results here—including the reason if something fails.")
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
    demo.load(auth_state, inputs=None, outputs=[auth_status, sign_in_link, sign_out_link])
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
        ],
        outputs=[status, output_files, manifest, build_log],
        api_name="build",
        concurrency_limit=1,
    )

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1).launch(css=CSS, js=INIT_JS, show_error=True)
