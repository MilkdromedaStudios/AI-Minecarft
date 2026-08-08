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

A Hugging Face Space for generating editable Minecraft projects with
[`moonshotai/Kimi-K3`](https://huggingface.co/moonshotai/Kimi-K3).

## What it supports

- **Mods:** Fabric, Forge, NeoForge, Quilt
- **Server plugins:** Paper, Purpur
- **Content packs:** resource packs and shader packs
- **Minecraft versions:** populated live from Mojang's Java version manifest, including releases and snapshots
- **Import as a base:** ZIP, JAR, pack archive, or uploaded project folder
- **Light + dark UI**
- **Hugging Face OAuth:** visitors use their own HF inference access instead of a shared public API key

## Hosting and “free”

BlockSmith is deployed as a Hugging Face **ZeroGPU Gradio Space** so it can be hosted by an eligible free personal account. The app itself does not request ZeroGPU compute: Kimi K3 runs through Hugging Face Inference Providers instead of loading the 2.8T-parameter model inside this Space.

The Space itself has no paywall. Kimi K3 requests use the signed-in visitor's Hugging Face Inference Providers allowance/credits. Hugging Face quotas and provider availability can change, so this is not a promise of unlimited free inference.

## Build behavior

Resource packs and shader packs are returned as directly usable ZIPs.

Java mods/plugins are returned as source-project ZIPs containing normal build files. BlockSmith
**does not execute AI-generated Gradle/Maven/shell scripts on the public server**, because doing so
would run untrusted code next to user authentication credentials. Review the generated project,
then compile it locally or in your own CI.

## Imported JARs

A JAR is a ZIP container. BlockSmith can inspect text resources and metadata inside it, but it
does not decompile or execute `.class` bytecode. For deep code changes, upload a source JAR or
source project ZIP.

## API / agents

Gradio automatically exposes API metadata and Hugging Face exposes an `agents.md` endpoint for
compatible Spaces, so coding agents can call this Space after deployment.
