# BlockSmith

BlockSmith is a Hugging Face Space that uses `moonshotai/Kimi-K3` to generate Minecraft mods, plugins, resource packs, and shader packs.

## Supported targets

- Fabric
- Forge
- NeoForge
- Quilt
- Paper
- Purpur
- Resource packs
- Shader packs
- Mojang releases and snapshots discovered live

Users can optionally upload an existing ZIP, JAR, pack, or project folder as a starting point. The Space supports light and dark mode and uses Hugging Face OAuth so visitors can run inference with their own Hugging Face access.

## Repository layout

- `space/` — the complete Gradio Space
- `.github/workflows/sync-blocksmith-space.yml` — validates and automatically deploys `space/` to `RespawnerzStudioz/BlockSmith-Minecraft`

## Free Hugging Face deployment

Add a write-capable Hugging Face access token to this repository as the Actions secret `HF_TOKEN`.

The GitHub workflow uses the current Hugging Face `hf` CLI directly. It creates the Space as a **Gradio ZeroGPU Space** (`zero-a10g`), forces an existing Space to stay on ZeroGPU, mirrors the `space/` directory, and waits for the deployed app to become healthy.

BlockSmith does not run Kimi K3 on the Space GPU. Kimi is called through Hugging Face Inference Providers using each signed-in visitor's OAuth inference access, so normal BlockSmith requests do not need a `@spaces.GPU` allocation.

Before every deployment the workflow also compiles the Python files, runs the builder tests, and imports the Gradio app as a smoke test.

The previous Minecraft YOLO/Mineflayer experiment has been removed from this repository.
