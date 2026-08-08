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
- `.github/workflows/sync-blocksmith-space.yml` — automatically syncs `space/` to `RespawnerzStudioz/BlockSmith-Minecraft`

## Deployment

Add a write-capable Hugging Face access token to this repository as the Actions secret `HF_TOKEN`. Pushes to `main` that change `space/` or the sync workflow will then deploy the Space.

The previous Minecraft YOLO/Mineflayer experiment has been removed from this repository.
