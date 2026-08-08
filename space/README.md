---
title: BlockSmith — Kimi K3 Minecraft Builder
emoji: ⛏️
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: 6.20.0
python_version: 3.12.12
app_file: app.py
pinned: false
license: mit
hf_oauth: true
hf_oauth_expiration_minutes: 480
hf_oauth_scopes:
  - inference-api
tags:
  - minecraft
  - kimi-k3
  - code-generation
  - gradio
  - zerogpu
  - agents
short_description: Build Minecraft mods, plugins, packs with Kimi K3.
---

# ⛏️ BlockSmith

BlockSmith generates, builds, repairs, and validates Minecraft projects with
[`moonshotai/Kimi-K3`](https://huggingface.co/moonshotai/Kimi-K3).

## What it supports

- **Mods:** Fabric, Forge, NeoForge, Quilt
- **Server plugins:** Paper, Purpur
- **Content packs:** resource packs and shader packs
- **Minecraft versions:** populated live from Mojang's Java version manifest, including releases and snapshots
- **Import as a base:** ZIP, JAR, pack archive, or uploaded project folder
- **Light + dark UI** with a persistent toggle
- **Detailed errors and logs:** failures are shown in the page instead of a generic `Error`
- **Hugging Face OAuth:** visitors use their own HF inference access instead of a shared public API key

## Automatic JAR builds

For Java mods and plugins, BlockSmith can return:

- **JAR + Source**
- **JAR only**
- **Source only**

When JAR output is selected, BlockSmith generates source with Kimi K3, compiles it, and if the
compiler reports errors, feeds those errors back to Kimi for another repair pass. It makes up to
**3 build/repair attempts** before falling back to the source project with the complete compiler log.

For security, BlockSmith **does not execute AI-written Gradle/Maven/wrapper files**. Before a build,
AI-generated build-system files are discarded and replaced with BlockSmith-owned scaffolding for the
selected loader/platform. The compilation subprocess receives a stripped environment without the
visitor's Hugging Face OAuth token. Required JDKs and Gradle distributions are downloaded from their
official distribution services with checksum verification when needed.

## Pack validation

**Resource packs** are checked for a valid `pack.mcmeta` and basic `assets/` structure before download.

**Shader packs** are checked for a conventional `shaders/` layout, missing/cyclic `#include` files,
and GLSL syntax with `glslangValidator` when the shader stage can be determined. Validator failures
are fed back to Kimi for up to 3 repair attempts.

Static shader validation cannot prove that a shader looks exactly as intended inside Minecraft,
Iris, or OptiFine. A true visual test would require launching the target Minecraft client and shader
loader. BlockSmith reports this limitation rather than claiming a visual test it did not perform.

## Hosting and inference

BlockSmith is deployed as a Hugging Face **ZeroGPU Gradio Space**. Kimi K3 itself runs through
Hugging Face Inference Providers rather than loading the model in the Space. The ZeroGPU marker exists
only to satisfy the free ZeroGPU hosting tier and is not called by normal BlockSmith builds.

The Space itself has no app paywall. Kimi K3 generation/repair requests use the signed-in visitor's
Hugging Face Inference Providers allowance or credits, and provider availability/quotas can change.

## Imported JARs

A JAR is a ZIP container. BlockSmith can inspect its text resources and metadata but does not
decompile or execute `.class` bytecode. For deep code changes, upload a source JAR or source project ZIP.

## API / agents

Gradio exposes the build API, and Hugging Face exposes an `agents.md` endpoint for compatible Spaces,
so coding agents can call BlockSmith after deployment.
