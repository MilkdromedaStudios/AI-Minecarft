from __future__ import annotations

from typing import Optional

import gradio as gr
import spaces

from minecraft_builder import KIMI_MODEL, build_project, list_minecraft_versions, loader_note

CSS = r"""
:root {
  --mc-bg: #f7f8fb;
  --mc-panel: #ffffff;
  --mc-panel-2: #eef2f7;
  --mc-text: #172033;
  --mc-muted: #667085;
  --mc-border: #d8dee9;
  --mc-accent: #6b7cff;
  --mc-accent-2: #7c3aed;
  --mc-success: #16a34a;
  --mc-shadow: 0 16px 45px rgba(15,23,42,.08);
}
.dark {
  --mc-bg: #090d15;
  --mc-panel: #111827;
  --mc-panel-2: #172033;
  --mc-text: #f8fafc;
  --mc-muted: #9ca3af;
  --mc-border: #263244;
  --mc-accent: #8b9cff;
  --mc-accent-2: #a78bfa;
  --mc-success: #4ade80;
  --mc-shadow: 0 16px 45px rgba(0,0,0,.35);
}
.gradio-container {
  max-width: 1500px !important;
  background: var(--mc-bg) !important;
  color: var(--mc-text) !important;
}
#hero, .mc-card {
  border: 1px solid var(--mc-border);
  background: var(--mc-panel);
  box-shadow: var(--mc-shadow);
  border-radius: 18px;
}
#hero { padding: 22px 26px; margin-bottom: 14px; }
#hero h1 { margin: 0; font-size: clamp(28px,4vw,46px); }
#hero p { color: var(--mc-muted); font-size: 16px; }
.mc-badge {
  display:inline-block; padding:5px 10px; margin:3px;
  border-radius:999px; border:1px solid var(--mc-border);
  background:var(--mc-panel-2); color:var(--mc-text); font-size:12px;
}
#theme-toggle {
  float:right; border:1px solid var(--mc-border); background:var(--mc-panel-2);
  color:var(--mc-text); border-radius:999px; padding:8px 12px; cursor:pointer;
}
#build-btn button { font-weight: 750; }
footer { visibility:hidden; }
"""

JS = r"""
() => {
  const saved = localStorage.getItem("mc-theme");
  const darkPreferred = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  if (saved === "dark" || (!saved && darkPreferred)) document.documentElement.classList.add("dark");
  function bindToggle() {
    const btn = document.getElementById("theme-toggle");
    if (!btn || btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.onclick = () => {
      document.documentElement.classList.toggle("dark");
      localStorage.setItem("mc-theme", document.documentElement.classList.contains("dark") ? "dark" : "light");
      btn.textContent = document.documentElement.classList.contains("dark") ? "☀️ Light" : "🌙 Dark";
    };
    btn.textContent = document.documentElement.classList.contains("dark") ? "☀️ Light" : "🌙 Dark";
  }
  bindToggle();
  new MutationObserver(bindToggle).observe(document.body, {subtree:true, childList:true});
}
"""

ARTIFACTS = ["Minecraft mod", "Server plugin", "Resource pack", "Shader pack"]


@spaces.GPU(duration=1)
def _zerogpu_marker() -> str:
    """ZeroGPU registration marker; normal BlockSmith requests never call this."""
    return "BlockSmith uses remote Hugging Face Inference Providers."


def refresh_versions():
    versions = list_minecraft_versions()
    default = versions[0] if versions else "latest"
    return gr.update(choices=versions, value=default), f"Loaded **{len(versions)}** Mojang versions (releases + snapshots)."


def on_artifact_change(kind: str):
    if kind == "Minecraft mod":
        return gr.update(choices=["Fabric", "Forge", "NeoForge", "Quilt"], value="Fabric")
    if kind == "Server plugin":
        return gr.update(choices=["Paper", "Purpur"], value="Paper")
    return gr.update(choices=["Vanilla / N/A"], value="Vanilla / N/A")


def explain_loader(loader: str, version: str):
    return loader_note(loader, version)


def run_builder(
    project_name: str,
    artifact_kind: str,
    loader: str,
    version: str,
    prompt: str,
    base_archive,
    base_folder,
    include_readme: bool,
    oauth_token: Optional[gr.OAuthToken],
):
    token = oauth_token.token if oauth_token else None
    if not token:
        raise gr.Error("Sign in with Hugging Face first so Kimi K3 can use your own HF inference quota.")
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
    )


with gr.Blocks(title="BlockSmith — Kimi K3 Minecraft Builder") as demo:
    gr.HTML(
        f"""
        <section id="hero">
          <button id="theme-toggle">🌙 Dark</button>
          <h1>⛏️ BlockSmith</h1>
          <p>Generate Minecraft mods, plugins, resource packs, and shader packs with
          <b>{KIMI_MODEL}</b> through Hugging Face.</p>
          <div>
            <span class="mc-badge">Fabric</span><span class="mc-badge">Forge</span>
            <span class="mc-badge">NeoForge</span><span class="mc-badge">Quilt</span>
            <span class="mc-badge">Paper</span><span class="mc-badge">Purpur</span>
            <span class="mc-badge">Releases + snapshots</span>
          </div>
        </section>
        """
    )

    with gr.Row():
        with gr.Column(scale=3, elem_classes="mc-card"):
            gr.Markdown("### 1. Sign in")
            gr.Markdown(
                "The app uses **your Hugging Face inference access** for Kimi K3, so the Space owner does not need to expose a shared API key."
            )
            gr.LoginButton()

            gr.Markdown("### 2. Choose the target")
            with gr.Row():
                project_name = gr.Textbox(
                    label="Project name", value="MyAwesomePack", placeholder="e.g. BetterCaves", scale=2
                )
                artifact_kind = gr.Dropdown(
                    ARTIFACTS, value="Minecraft mod", label="What are you making?", scale=2
                )
            with gr.Row():
                loader = gr.Dropdown(
                    ["Fabric", "Forge", "NeoForge", "Quilt"], value="Fabric", label="Loader / platform"
                )
                version = gr.Dropdown(
                    ["latest"], value="latest", allow_custom_value=True, label="Minecraft version",
                    info="Populated live from Mojang, including snapshots."
                )
            refresh = gr.Button("↻ Refresh Minecraft versions", size="sm")
            version_status = gr.Markdown("Version list will load when the app opens.")
            compatibility = gr.Markdown()

            gr.Markdown("### 3. Describe what you want")
            prompt = gr.Textbox(
                label="Build instructions", lines=9,
                placeholder=(
                    "Example: Make a Fabric mod that adds a grappling hook crafted from iron, "
                    "string, and an ender pearl. Add a configurable max range and particles."
                ),
            )

            gr.Markdown("### 4. Optional: improve an existing project")
            with gr.Tabs():
                with gr.Tab("ZIP / JAR / pack"):
                    base_archive = gr.File(
                        label="Upload ZIP, JAR, resource pack, shader pack, or source archive",
                        file_count="single", type="filepath"
                    )
                with gr.Tab("Folder"):
                    base_folder = gr.File(label="Upload a project folder", file_count="directory", type="filepath")
            include_readme = gr.Checkbox(value=True, label="Include README + build/use instructions")
            build_btn = gr.Button("✨ Build with Kimi K3", variant="primary", elem_id="build-btn")

        with gr.Column(scale=2, elem_classes="mc-card"):
            gr.Markdown("### Build result")
            status = gr.Markdown(
                "Your generated project will appear here. Code projects are returned as safe source-project ZIPs; resource/shader packs are directly usable ZIPs."
            )
            output_file = gr.File(label="Download build")
            manifest = gr.JSON(label="Generated file manifest")
            gr.Markdown(
                """
                **Safety / compatibility:** imported archives are inspected but never executed.
                AI-generated Gradle or shell scripts are packaged, not run on the Space.
                Loader/version support changes over time, so BlockSmith checks live metadata where possible
                and reports compatibility rather than pretending every historical loader supports every snapshot.
                """
            )

    artifact_kind.change(on_artifact_change, inputs=artifact_kind, outputs=loader)
    loader.change(explain_loader, inputs=[loader, version], outputs=compatibility)
    version.change(explain_loader, inputs=[loader, version], outputs=compatibility)
    refresh.click(refresh_versions, outputs=[version, version_status], api_name="refresh_versions")
    demo.load(refresh_versions, outputs=[version, version_status])
    build_btn.click(
        run_builder,
        inputs=[project_name, artifact_kind, loader, version, prompt, base_archive, base_folder, include_readme],
        outputs=[status, output_file, manifest],
        api_name="build",
        concurrency_limit=2,
    )

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=2).launch(css=CSS, js=JS)
