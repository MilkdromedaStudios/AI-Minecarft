from __future__ import annotations

import json
import os
import re
import resource
import shutil
import subprocess
import tempfile
import traceback
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional
from xml.etree import ElementTree

import requests
from huggingface_hub import InferenceClient

KIMI_MODEL = "moonshotai/Kimi-K3"

MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FABRIC_GAMES = "https://meta.fabricmc.net/v2/versions/game"
FABRIC_LOADER_FOR_GAME = "https://meta.fabricmc.net/v2/versions/loader/{version}"
QUILT_GAMES = "https://meta.quiltmc.org/v3/versions/game"
QUILT_LOADER_FOR_GAME = "https://meta.quiltmc.org/v3/versions/loader/{version}"
PAPER_PROJECT = "https://api.papermc.io/v2/projects/paper"
PURPUR_PROJECT = "https://api.purpurmc.org/v2/purpur"
FORGE_META = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
NEOFORGE_META = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
FABRIC_LOOM_META = "https://maven.fabricmc.net/net/fabricmc/fabric-loom/maven-metadata.xml"
FABRIC_API_META = "https://maven.fabricmc.net/net/fabricmc/fabric-api/fabric-api/maven-metadata.xml"
QUILT_LOOM_META = "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-loom/maven-metadata.xml"
MODDEV_META = "https://maven.neoforged.net/releases/net/neoforged/moddev/net.neoforged.moddev.gradle.plugin/maven-metadata.xml"

MAX_IMPORT_FILES = 220
MAX_IMPORT_BYTES = 3_000_000
MAX_SINGLE_TEXT = 120_000
MAX_MODEL_FILES = 350
MAX_MODEL_TEXT_BYTES = 12_000_000
MAX_REPAIR_LOG_CHARS = 14000
BUILD_TIMEOUT_SECONDS = 300
MAX_REPAIR_ATTEMPTS = 3
GRADLE_CACHE = Path("/tmp/blocksmith-gradle-cache")
TOOL_CACHE = Path("/tmp/blocksmith-tools")

ALLOWED_TEXT_SUFFIXES = {
    ".java", ".kt", ".kts", ".json", ".mcmeta", ".toml", ".yaml", ".yml", ".xml",
    ".properties", ".gradle", ".md", ".txt", ".glsl", ".fsh", ".vsh", ".gsh", ".csh",
    ".cfg", ".conf", ".js", ".ts", ".py", ".css", ".html", ".lang", ".mcfunction",
}
BUILD_FILE_NAMES = {
    "gradlew", "gradlew.bat", "build.gradle", "build.gradle.kts", "settings.gradle",
    "settings.gradle.kts", "gradle.properties", "pom.xml",
}


class BlockSmithError(RuntimeError):
    """A user-displayable BlockSmith failure."""


def _get_json(url: str, timeout: float = 12.0):
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "BlockSmith-HF-Space/2.0"})
    r.raise_for_status()
    return r.json()


def _get_text(url: str, timeout: float = 12.0) -> str:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "BlockSmith-HF-Space/2.0"})
    r.raise_for_status()
    return r.text


def list_minecraft_versions() -> list[str]:
    try:
        data = _get_json(MOJANG_MANIFEST)
        return [v["id"] for v in data.get("versions", []) if v.get("id")]
    except Exception:
        return ["latest"]


def resolve_minecraft_version(version: str) -> str:
    if version and version != "latest":
        return version
    versions = list_minecraft_versions()
    return versions[0] if versions and versions[0] != "latest" else "latest"


def _xml_versions(url: str) -> list[str]:
    try:
        root = ElementTree.fromstring(_get_text(url))
        return [n.text for n in root.findall(".//version") if n.text]
    except Exception:
        return []


def _latest_xml_version(url: str, *, contains: str | None = None) -> Optional[str]:
    versions = _xml_versions(url)
    if contains:
        versions = [v for v in versions if contains in v]
    return versions[-1] if versions else None


def loader_note(loader: str, version: str) -> str:
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
            ok = version in _get_json(PAPER_PROJECT).get("versions", [])
        elif loader == "Purpur":
            ok = version in _get_json(PURPUR_PROJECT).get("versions", [])
        elif loader == "Forge":
            ok = any(v.startswith(version + "-") for v in _xml_versions(FORGE_META))
        elif loader == "NeoForge":
            compact = version[2:] if version.startswith("1.") else version
            ok = any(v.startswith(compact + ".") or v.startswith(version + ".") for v in _xml_versions(NEOFORGE_META))
        else:
            return "ℹ️ Compatibility is not known for this target."
        if ok:
            return f"✅ **{loader}** currently publishes metadata compatible with **Minecraft {version}**."
        return f"⚠️ I could not confirm a published **{loader}** build for **Minecraft {version}**. Source generation can still proceed, but automatic JAR compilation may not be available."
    except Exception as exc:
        return f"ℹ️ Live {loader} compatibility check is temporarily unavailable: `{type(exc).__name__}`."


def _safe_relpath(name: str) -> Optional[str]:
    name = name.replace("\\", "/").lstrip("/")
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or len(p.parts) > 24:
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
                if suffix not in ALLOWED_TEXT_SUFFIXES and Path(rel).name not in BUILD_FILE_NAMES:
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
                notes.append("Compiled .class bytecode was not decompiled. Text resources/metadata were imported; upload a source project for deep code edits.")
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
        if p.suffix.lower() not in ALLOWED_TEXT_SUFFIXES and p.name not in BUILD_FILE_NAMES:
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
        return _summarize_zip(Path(base_archive))
    return _summarize_folder(base_folder)


SYSTEM_PROMPT = r"""
You are BlockSmith, a senior Minecraft Java mod/plugin/resource-pack/shader engineer.
Return ONE strict JSON object and nothing else.

Generate a complete editable project for the exact artifact, loader/platform, and Minecraft version requested.
The server uses a trusted build scaffold for Java projects, so focus on src/**, resources, and loader metadata.
Do not try to replace or customize Gradle/Maven wrapper/build-system files unless the user explicitly asks for source-only build customization.

Required JSON schema:
{
  "summary": "short human-readable summary",
  "warnings": ["zero or more concise warnings"],
  "files": [{"path": "relative/path.ext", "content": "full UTF-8 file content"}]
}

Rules:
- Never use absolute paths or ../ paths.
- Fabric: include fabric.mod.json. Quilt: include quilt.mod.json. Forge/NeoForge: include correct META-INF metadata. Paper/Purpur: include plugin.yml unless a Paper manifest is truly required.
- Resource packs must contain pack.mcmeta and assets/...; shader packs should use a conventional shaders/ layout.
- Target the selected version exactly. If a loader does not publish for that version, warn instead of pretending.
- If an existing project was supplied, preserve its intent and improve/port it.
- Text/source only. No base64 binaries.
- No secrets, telemetry, miners, remote-control code, self-updaters, or runtime code downloading.
- Keep IDs/namespaces lowercase and filesystem-safe.
- For mods/plugins, generate Java source rather than Kotlin so the trusted compiler scaffold can build it consistently.
"""

REPAIR_PROMPT = r"""
You are repairing a generated Minecraft project after an automated compiler or validator failed.
Return ONE strict JSON object with the same schema: summary, warnings, files.
Return the COMPLETE corrected project, not a patch.
Fix the reported errors while preserving the user's requested behavior and exact Minecraft version/loader.
Do not add Gradle/Maven wrapper or build-system files; BlockSmith supplies a trusted build scaffold.
Do not hide errors by deleting requested features unless no compatible API exists; if impossible, explain it in warnings.
"""


def _prompt_payload(project_name, artifact_kind, loader, minecraft_version, user_prompt, imported_files, import_notes, include_readme) -> str:
    return "Build this Minecraft project.\n" + json.dumps({
        "project_name": project_name,
        "artifact_kind": artifact_kind,
        "loader": loader,
        "minecraft_version": minecraft_version,
        "request": user_prompt,
        "include_readme": include_readme,
        "import_notes": import_notes,
        "existing_files": imported_files,
    }, ensure_ascii=False)


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
        raise BlockSmithError("Kimi returned a response that was not valid project JSON.")


def _sanitize_files(raw_files) -> tuple[list[dict], list[str]]:
    safe: list[dict] = []
    warnings: list[str] = []
    seen = set()
    total = 0
    if not isinstance(raw_files, list):
        raise BlockSmithError("Kimi's response did not contain a files list.")
    for item in raw_files[:MAX_MODEL_FILES]:
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
        encoded = content.encode("utf-8")
        if len(encoded) > 800_000:
            warnings.append(f"Dropped oversized text file: {rel}")
            continue
        total += len(encoded)
        if total > MAX_MODEL_TEXT_BYTES:
            warnings.append("Output exceeded the 12 MB text-project limit; remaining files were dropped.")
            break
        seen.add(rel)
        safe.append({"path": rel, "content": content})
    if not safe:
        raise BlockSmithError("Kimi returned no usable project files.")
    return safe, warnings


def _model_call(client: InferenceClient, system: str, user: str, max_tokens: int = 20000) -> dict:
    try:
        response = client.chat.completions.create(
            model=KIMI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        text = response.choices[0].message.content
        return _extract_json(text)
    except BlockSmithError:
        raise
    except Exception as exc:
        msg = str(exc).strip() or repr(exc)
        hint = ""
        low = msg.lower()
        if "402" in msg or "credit" in low or "payment" in low:
            hint = " Your Hugging Face Inference Providers credits may be exhausted."
        elif "429" in msg or "rate" in low:
            hint = " The inference provider is rate-limiting requests; try again shortly."
        elif "401" in msg or "403" in msg or "unauthor" in low or "forbidden" in low:
            hint = " Sign out/in to Hugging Face and make sure the Space OAuth grant includes inference access."
        raise BlockSmithError(f"Kimi K3 inference failed: {type(exc).__name__}: {msg}.{hint}") from exc


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
    if loader in {"Paper", "Purpur"} and not any(p.endswith("plugin.yml") or p.endswith("paper-plugin.yml") for p in low):
        out.append(f"{loader} plugin is missing plugin.yml/paper-plugin.yml.")
    return out


def _file_map(files: list[dict]) -> dict[str, str]:
    return {f["path"]: f["content"] for f in files}


def _files_from_map(files: dict[str, str]) -> list[dict]:
    return [{"path": p, "content": c} for p, c in sorted(files.items())]


def _safe_mod_id(project_name: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", project_name.lower()).strip("_")
    if not s:
        s = "blocksmith_mod"
    if s[0].isdigit():
        s = "mod_" + s
    return s[:48]


def _java_release_for_mc(version: str) -> int:
    if version.startswith("26."):
        return 25
    m = re.match(r"1\.(\d+)(?:\.(\d+))?", version)
    if not m:
        return 21
    minor, patch = int(m.group(1)), int(m.group(2) or 0)
    if minor >= 20 and patch >= 5:
        return 21
    if minor >= 18:
        return 17
    if minor == 17:
        return 16
    return 8


def _select_loader_version(loader: str, mc: str) -> Optional[str]:
    if loader == "Fabric":
        try:
            rows = _get_json(FABRIC_LOADER_FOR_GAME.format(version=mc))
            if rows:
                return rows[0].get("loader", {}).get("version") or rows[0].get("version")
        except Exception:
            return None
    if loader == "Quilt":
        try:
            rows = _get_json(QUILT_LOADER_FOR_GAME.format(version=mc))
            if rows:
                return rows[0].get("loader", {}).get("version") or rows[0].get("version")
        except Exception:
            return None
    if loader == "Forge":
        versions = [v for v in _xml_versions(FORGE_META) if v.startswith(mc + "-")]
        return versions[-1] if versions else None
    if loader == "NeoForge":
        compact = mc[2:] if mc.startswith("1.") else mc
        versions = [v for v in _xml_versions(NEOFORGE_META) if v.startswith(compact + ".") or v.startswith(mc + ".")]
        return versions[-1] if versions else None
    return None


def _trusted_scaffold(project_name: str, loader: str, mc: str) -> tuple[dict[str, str], str, list[str]]:
    mod_id = _safe_mod_id(project_name)
    java_version = _java_release_for_mc(mc)
    notes: list[str] = []

    if loader in {"Paper", "Purpur"}:
        api_version = f"{mc}-R0.1-SNAPSHOT" if mc.startswith("1.") else f"{mc}.build.+"
        pom = f'''<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>dev.blocksmith.generated</groupId><artifactId>{mod_id}</artifactId><version>1.0.0</version>
  <properties><maven.compiler.release>{java_version}</maven.compiler.release><project.build.sourceEncoding>UTF-8</project.build.sourceEncoding></properties>
  <repositories><repository><id>papermc</id><url>https://repo.papermc.io/repository/maven-public/</url></repository></repositories>
  <dependencies><dependency><groupId>io.papermc.paper</groupId><artifactId>paper-api</artifactId><version>{api_version}</version><scope>provided</scope></dependency></dependencies>
  <build><plugins><plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-compiler-plugin</artifactId><version>3.14.1</version></plugin></plugins></build>
</project>'''
        return {"pom.xml": pom}, "mvn -q -DskipTests package", notes

    if loader == "Fabric":
        loader_version = _select_loader_version("Fabric", mc)
        loom_version = _latest_xml_version(FABRIC_LOOM_META)
        if not loader_version or not loom_version:
            raise BlockSmithError(f"Could not resolve Fabric Loader/Loom versions for Minecraft {mc}.")
        api_version = _latest_xml_version(FABRIC_API_META, contains=f"+{mc}")
        plugin_id = "net.fabricmc.fabric-loom" if not mc.startswith("1.") else "net.fabricmc.fabric-loom-remap"
        deps = f'''minecraft "com.mojang:minecraft:{mc}"
    mappings loom.officialMojangMappings()
    modImplementation "net.fabricmc:fabric-loader:{loader_version}"'''
        if api_version:
            deps += f'\n    modImplementation "net.fabricmc.fabric-api:fabric-api:{api_version}"'
        else:
            notes.append("No exact Fabric API artifact was found; compiled against Fabric Loader + Minecraft only.")
        build = f'''plugins {{ id '{plugin_id}' version '{loom_version}'; id 'maven-publish' }}
version = '1.0.0'; group = 'dev.blocksmith.generated'
base {{ archivesName = '{mod_id}' }}
repositories {{ mavenCentral(); maven {{ url = 'https://maven.fabricmc.net/' }} }}
dependencies {{ {deps} }}
java {{ toolchain.languageVersion = JavaLanguageVersion.of({java_version}) }}
'''
        settings = "pluginManagement { repositories { maven { url = 'https://maven.fabricmc.net/' }; gradlePluginPortal(); mavenCentral() } }\nrootProject.name='BlockSmithGenerated'\n"
        return {"settings.gradle": settings, "build.gradle": build, "gradle.properties": "org.gradle.jvmargs=-Xmx1536m\norg.gradle.daemon=false\n"}, "gradle build --no-daemon --stacktrace", notes

    if loader == "Quilt":
        loader_version = _select_loader_version("Quilt", mc)
        loom_version = _latest_xml_version(QUILT_LOOM_META)
        if not loader_version or not loom_version:
            raise BlockSmithError(f"Could not resolve Quilt Loader/Loom versions for Minecraft {mc}.")
        build = f'''plugins {{ id 'org.quiltmc.loom' version '{loom_version}'; id 'maven-publish' }}
version='1.0.0'; group='dev.blocksmith.generated'
base {{ archivesName = '{mod_id}' }}
repositories {{ mavenCentral(); maven {{ url='https://maven.quiltmc.org/repository/release/' }} }}
dependencies {{ minecraft "com.mojang:minecraft:{mc}"; mappings loom.officialMojangMappings(); modImplementation "org.quiltmc:quilt-loader:{loader_version}" }}
java {{ toolchain.languageVersion = JavaLanguageVersion.of({java_version}) }}
'''
        settings = "pluginManagement { repositories { maven { url='https://maven.quiltmc.org/repository/release/' }; gradlePluginPortal(); mavenCentral() } }\nrootProject.name='BlockSmithGenerated'\n"
        return {"settings.gradle": settings, "build.gradle": build, "gradle.properties": "org.gradle.jvmargs=-Xmx1536m\norg.gradle.daemon=false\n"}, "gradle build --no-daemon --stacktrace", notes

    if loader == "Forge":
        forge_version = _select_loader_version("Forge", mc)
        if not forge_version:
            raise BlockSmithError(f"Forge does not currently publish a build for Minecraft {mc}.")
        build = f'''plugins {{ id 'net.minecraftforge.gradle' version '[6.0,6.2)' }}
group='dev.blocksmith.generated'; version='1.0.0'
base {{ archivesName = '{mod_id}' }}
java.toolchain.languageVersion = JavaLanguageVersion.of({java_version})
minecraft {{ mappings channel: 'official', version: '{mc}' }}
repositories {{ mavenCentral() }}
dependencies {{ minecraft 'net.minecraftforge:forge:{forge_version}' }}
'''
        settings = "pluginManagement { repositories { maven { url='https://maven.minecraftforge.net/' }; gradlePluginPortal(); mavenCentral() } }\nrootProject.name='BlockSmithGenerated'\n"
        return {"settings.gradle": settings, "build.gradle": build, "gradle.properties": "org.gradle.jvmargs=-Xmx1536m\norg.gradle.daemon=false\n"}, "gradle build --no-daemon --stacktrace", notes

    if loader == "NeoForge":
        neo_version = _select_loader_version("NeoForge", mc)
        moddev_version = _latest_xml_version(MODDEV_META)
        if not neo_version or not moddev_version:
            raise BlockSmithError(f"Could not resolve NeoForge/ModDevGradle for Minecraft {mc}.")
        build = f'''plugins {{ id 'net.neoforged.moddev' version '{moddev_version}' }}
group='dev.blocksmith.generated'; version='1.0.0'
base {{ archivesName = '{mod_id}' }}
java.toolchain.languageVersion = JavaLanguageVersion.of({java_version})
neoForge {{ enable {{ version = '{neo_version}'; disableRecompilation = true }}; mods {{ {mod_id} {{ sourceSet sourceSets.main }} }} }}
'''
        settings = "pluginManagement { repositories { gradlePluginPortal(); maven { url='https://maven.neoforged.net/releases/' }; mavenCentral() } }\nrootProject.name='BlockSmithGenerated'\n"
        return {"settings.gradle": settings, "build.gradle": build, "gradle.properties": "org.gradle.jvmargs=-Xmx1536m\norg.gradle.daemon=false\n"}, "gradle build --no-daemon --stacktrace", notes

    raise BlockSmithError(f"Automatic JAR compilation is not configured for {loader}.")


def _gradle_version_for(loader: str, mc: str) -> str:
    if loader == "Fabric" and not mc.startswith("1."):
        return "9.2.1"
    return "8.14.3"


def _ensure_gradle(version: str) -> Path:
    TOOL_CACHE.mkdir(parents=True, exist_ok=True)
    root = TOOL_CACHE / f"gradle-{version}"
    exe = root / "bin" / "gradle"
    if exe.exists():
        return exe
    zip_path = TOOL_CACHE / f"gradle-{version}-bin.zip"
    url = f"https://services.gradle.org/distributions/gradle-{version}-bin.zip"
    sha_url = url + ".sha256"
    import hashlib
    expected = _get_text(sha_url, timeout=20).strip().split()[0]
    r = requests.get(url, timeout=90, headers={"User-Agent": "BlockSmith-HF-Space/2.0"})
    r.raise_for_status()
    data = r.content
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != expected.lower():
        raise BlockSmithError("Gradle download checksum verification failed.")
    zip_path.write_bytes(data)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(TOOL_CACHE)
    exe.chmod(0o755)
    return exe


def _materialize(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        safe = _safe_relpath(rel)
        if not safe:
            continue
        p = root / safe
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _ensure_jdk(feature: int) -> Path:
    """Download a checksum-verified Temurin JDK only when needed."""
    TOOL_CACHE.mkdir(parents=True, exist_ok=True)
    cached = TOOL_CACHE / f"jdk-{feature}"
    java = cached / "bin" / "java"
    if java.exists():
        return cached
    assets_url = (
        f"https://api.adoptium.net/v3/assets/latest/{feature}/hotspot"
        "?architecture=x64&image_type=jdk&jvm_impl=hotspot&os=linux&vendor=eclipse"
    )
    assets = _get_json(assets_url, timeout=30)
    if not assets:
        raise BlockSmithError(f"No Temurin JDK {feature} Linux/x64 build is currently available.")
    package = assets[0].get("binary", {}).get("package", {})
    url = package.get("link")
    expected = package.get("checksum")
    if not url or not expected:
        raise BlockSmithError(f"Adoptium did not provide a downloadable/checksummed JDK {feature} package.")
    r = requests.get(url, timeout=120, headers={"User-Agent": "BlockSmith-HF-Space/2.0"})
    r.raise_for_status()
    data = r.content
    import hashlib
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != str(expected).lower():
        raise BlockSmithError(f"JDK {feature} checksum verification failed.")
    archive = TOOL_CACHE / f"jdk-{feature}.tar.gz"
    archive.write_bytes(data)
    import tarfile
    extract = TOOL_CACHE / f"jdk-{feature}-extract"
    if extract.exists():
        shutil.rmtree(extract)
    extract.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            target = (extract / member.name).resolve()
            if not str(target).startswith(str(extract.resolve()) + os.sep):
                raise BlockSmithError("Unsafe path in JDK archive.")
        tf.extractall(extract)
    candidates = [d for d in extract.iterdir() if d.is_dir() and (d / "bin" / "java").exists()]
    if not candidates:
        raise BlockSmithError(f"Downloaded JDK {feature} archive did not contain a Java runtime.")
    if cached.exists():
        shutil.rmtree(cached)
    shutil.move(str(candidates[0]), str(cached))
    return cached


def _clean_build_env(root: Path, java_home: Path) -> dict[str, str]:
    home = Path("/tmp/blocksmith-build-home")
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": str(java_home / "bin") + os.pathsep + os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "CI": "true",
        "GRADLE_USER_HOME": str(GRADLE_CACHE),
        "MAVEN_OPTS": "-Xmx1536m",
    }
    env["JAVA_HOME"] = str(java_home)
    return env


def _limit_child() -> None:
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (BUILD_TIMEOUT_SECONDS + 30, BUILD_TIMEOUT_SECONDS + 30))
        resource.setrlimit(resource.RLIMIT_FSIZE, (500_000_000, 500_000_000))
        resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
    except Exception:
        pass


def _run_build(root: Path, loader: str, mc: str, command_hint: str) -> tuple[bool, str, Optional[Path]]:
    java_feature = _java_release_for_mc(mc)
    java_home = _ensure_jdk(java_feature)
    env = _clean_build_env(root, java_home)
    if command_hint.startswith("mvn"):
        cmd = ["mvn", "-B", "-DskipTests", "package"]
    else:
        gradle = _ensure_gradle(_gradle_version_for(loader, mc))
        cmd = [str(gradle), "build", "--no-daemon", "--stacktrace", "--console=plain"]
    try:
        proc = subprocess.run(
            cmd, cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=BUILD_TIMEOUT_SECONDS, preexec_fn=_limit_child,
        )
        log = proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        return False, f"Build timed out after {BUILD_TIMEOUT_SECONDS}s.\n{exc.stdout or ''}", None
    except FileNotFoundError as exc:
        return False, f"Build tool is not installed: {exc}", None
    except Exception as exc:
        return False, f"Build process could not start: {type(exc).__name__}: {exc}", None
    jars = []
    for base in (root / "build" / "libs", root / "target"):
        if base.exists():
            jars.extend(p for p in base.glob("*.jar") if not any(x in p.name.lower() for x in ("sources", "javadoc", "dev", "plain")))
    jar = min(jars, key=lambda p: len(p.name)) if jars else None
    return proc.returncode == 0 and jar is not None, log, jar


def _prepare_compile_files(files: list[dict], scaffold: dict[str, str]) -> dict[str, str]:
    data = _file_map(files)
    for name in list(data):
        if Path(name).name in BUILD_FILE_NAMES or name.startswith("gradle/wrapper/"):
            data.pop(name, None)
    data.update(scaffold)
    return data


def _repair_project(client: InferenceClient, *, project_name: str, artifact_kind: str, loader: str, mc: str, user_prompt: str, files: dict[str, str], failure_log: str) -> tuple[list[dict], list[str]]:
    editable = [{"path": p, "content": c} for p, c in files.items() if Path(p).name not in BUILD_FILE_NAMES and not p.startswith("gradle/")]
    payload = {
        "project_name": project_name,
        "artifact_kind": artifact_kind,
        "loader": loader,
        "minecraft_version": mc,
        "original_request": user_prompt,
        "failure_log": failure_log[-MAX_REPAIR_LOG_CHARS:],
        "current_files": editable,
    }
    parsed = _model_call(client, REPAIR_PROMPT, json.dumps(payload, ensure_ascii=False))
    repaired, warnings = _sanitize_files(parsed.get("files"))
    return repaired, list(parsed.get("warnings") or []) + warnings


def _write_zip(project_name: str, files: dict[str, str], info: str, suffix: str = "source") -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "minecraft-project"
    out_dir = Path(tempfile.mkdtemp(prefix="blocksmith-out-"))
    out_path = out_dir / f"{safe_name}-{suffix}.zip"
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as zf:
        for path, content in sorted(files.items()):
            zf.writestr(path, content)
        zf.writestr("BLOCKSMITH_BUILD_INFO.txt", info)
    return str(out_path)


def _copy_output_file(src: Path, project_name: str) -> str:
    out_dir = Path(tempfile.mkdtemp(prefix="blocksmith-jar-"))
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "minecraft-project"
    dst = out_dir / f"{safe_name}.jar"
    shutil.copy2(src, dst)
    return str(dst)


def _resolve_include(path: str, current: str, files: dict[str, str]) -> Optional[str]:
    candidate = path.strip().replace("\\", "/")
    if candidate.startswith("/"):
        candidate = "shaders" + candidate
    else:
        candidate = str(PurePosixPath(current).parent / candidate)
    candidate = str(PurePosixPath(candidate))
    return candidate if candidate in files else None


def _expand_shader_includes(path: str, files: dict[str, str], stack: Optional[list[str]] = None) -> tuple[str, list[str]]:
    stack = list(stack or [])
    if path in stack:
        return files[path], [f"Include cycle detected: {' -> '.join(stack + [path])}"]
    stack.append(path)
    errors: list[str] = []
    out: list[str] = []
    include_re = re.compile(r'^\s*#include\s+["<]([^">]+)[">]')
    for line in files[path].splitlines():
        m = include_re.match(line)
        if not m:
            out.append(line)
            continue
        target = _resolve_include(m.group(1), path, files)
        if not target:
            errors.append(f"{path}: missing include {m.group(1)}")
            continue
        expanded, sub_errors = _expand_shader_includes(target, files, stack)
        errors.extend(sub_errors)
        out.append(f"// begin include {target}")
        out.append(expanded)
        out.append(f"// end include {target}")
    return "\n".join(out), errors


def validate_shader_pack(files: list[dict]) -> tuple[bool, str]:
    fmap = _file_map(files)
    shader_paths = [p for p in fmap if p.startswith("shaders/") and Path(p).suffix.lower() in {".vsh", ".fsh", ".gsh", ".csh", ".glsl"}]
    log: list[str] = ["BlockSmith shader validation"]
    if not shader_paths:
        return False, "No shader source files were found under shaders/."
    syntax_errors = 0
    validator = shutil.which("glslangValidator")
    if not validator:
        log.append("glslangValidator is unavailable; performing structure/include validation only.")
    with tempfile.TemporaryDirectory(prefix="blocksmith-shader-") as td:
        td_path = Path(td)
        for path in shader_paths:
            expanded, include_errors = _expand_shader_includes(path, fmap)
            if include_errors:
                syntax_errors += len(include_errors)
                log.extend(include_errors)
            suffix = Path(path).suffix.lower()
            stage = {".vsh": "vert", ".fsh": "frag", ".gsh": "geom", ".csh": "comp"}.get(suffix)
            if validator and stage:
                temp = td_path / (re.sub(r"[^A-Za-z0-9_.-]+", "_", path) + suffix)
                temp.write_text(expanded, encoding="utf-8")
                proc = subprocess.run([validator, "-S", stage, str(temp)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
                if proc.returncode:
                    syntax_errors += 1
                    log.append(f"FAILED {path} ({stage})\n{proc.stdout[-5000:]}")
                else:
                    log.append(f"PASS {path} ({stage})")
    stems_v = {str(PurePosixPath(p).with_suffix("")) for p in shader_paths if p.endswith(".vsh")}
    stems_f = {str(PurePosixPath(p).with_suffix("")) for p in shader_paths if p.endswith(".fsh")}
    unpaired = sorted(stems_v ^ stems_f)
    if unpaired:
        log.append("Note: unpaired vertex/fragment program stems: " + ", ".join(unpaired[:20]))
    if syntax_errors:
        log.append(f"Validation failed with {syntax_errors} error(s).")
        return False, "\n".join(log)
    log.append("Static shader validation passed. This checks structure/includes/GLSL syntax, not final visual appearance inside Minecraft/Iris/OptiFine.")
    return True, "\n".join(log)


def validate_resource_pack(files: list[dict]) -> tuple[bool, str]:
    fmap = _file_map(files)
    errors = []
    if "pack.mcmeta" not in fmap:
        errors.append("Missing pack.mcmeta")
    else:
        try:
            json.loads(fmap["pack.mcmeta"])
        except Exception as exc:
            errors.append(f"pack.mcmeta is not valid JSON: {exc}")
    if not any(p.startswith("assets/") for p in fmap):
        errors.append("No assets/ directory content was generated")
    return (not errors, "Resource-pack validation passed." if not errors else "\n".join(errors))


def _source_info(status: str, log: str) -> str:
    return status.replace("**", "") + "\n\n--- BUILD / VALIDATION LOG ---\n" + log


def build_project(
    *, project_name: str, artifact_kind: str, loader: str, minecraft_version: str, user_prompt: str,
    base_archive, base_folder, include_readme: bool, hf_token: str, output_preference: str = "JAR + Source",
):
    if not user_prompt or len(user_prompt.strip()) < 8:
        raise BlockSmithError("Describe what you want the project to do in a little more detail.")
    if not hf_token:
        raise BlockSmithError("No Hugging Face OAuth token was received. Sign in with Hugging Face and try again.")

    project_name = (project_name or "MinecraftProject").strip()[:80]
    mc = resolve_minecraft_version(minecraft_version)
    imported, import_notes = inspect_base(base_archive, base_folder)
    client = InferenceClient(provider="auto", api_key=hf_token, timeout=180)

    parsed = _model_call(client, SYSTEM_PROMPT, _prompt_payload(project_name, artifact_kind, loader, mc, user_prompt, imported, import_notes, include_readme))
    files, sanitize_warnings = _sanitize_files(parsed.get("files"))
    warnings = list(import_notes) + list(parsed.get("warnings") or []) + sanitize_warnings
    warnings += _required_file_warnings(artifact_kind, loader, {f["path"] for f in files})
    summary = str(parsed.get("summary") or f"Generated {project_name}.")
    build_log_parts = [f"Model: {KIMI_MODEL}", f"Target: {artifact_kind} / {loader} / Minecraft {mc}"]
    outputs: list[str] = []
    manifest: dict = {"model": KIMI_MODEL, "minecraft_version": mc, "loader": loader, "artifact_kind": artifact_kind, "summary": summary}

    if artifact_kind in {"Minecraft mod", "Server plugin"}:
        source_map = _file_map(files)
        jar_path: Optional[str] = None
        compile_ok = False
        scaffold_notes: list[str] = []
        if output_preference != "Source only":
            try:
                scaffold, command_hint, scaffold_notes = _trusted_scaffold(project_name, loader, mc)
                warnings += scaffold_notes
                for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
                    compile_map = _prepare_compile_files(_files_from_map(source_map), scaffold)
                    with tempfile.TemporaryDirectory(prefix="blocksmith-build-") as td:
                        root = Path(td)
                        _materialize(root, compile_map)
                        ok, build_log, jar = _run_build(root, loader, mc, command_hint)
                        build_log_parts.append(f"\n=== Compile attempt {attempt}/{MAX_REPAIR_ATTEMPTS} ===\n{build_log[-20000:]}")
                        if ok and jar:
                            jar_path = _copy_output_file(jar, project_name)
                            compile_ok = True
                            source_map = compile_map
                            break
                    if attempt < MAX_REPAIR_ATTEMPTS:
                        repaired, repair_warnings = _repair_project(
                            client, project_name=project_name, artifact_kind=artifact_kind, loader=loader, mc=mc,
                            user_prompt=user_prompt, files=source_map, failure_log=build_log,
                        )
                        warnings += repair_warnings
                        source_map = _file_map(repaired)
                if not compile_ok:
                    warnings.append(f"Automatic compilation did not produce a JAR after {MAX_REPAIR_ATTEMPTS} attempts. Source is still available with the full compiler log.")
            except Exception as exc:
                warnings.append(f"Automatic JAR build unavailable: {type(exc).__name__}: {exc}")
                build_log_parts.append("\n=== JAR build setup error ===\n" + traceback.format_exc(limit=8))
        else:
            build_log_parts.append("Source-only output selected; compilation was skipped.")

        status_bits = [f"Generated **{len(source_map)} files** for **Minecraft {mc} / {loader}**."]
        if compile_ok:
            status_bits.append("✅ **Compiled JAR produced successfully** after automated build/repair. You can download the JAR or the complete source project.")
        elif output_preference != "Source only":
            status_bits.append("⚠️ A JAR could not be produced automatically. The source ZIP and detailed build log are provided instead of a generic error.")
        else:
            status_bits.append("Source ZIP generated; automatic compilation was skipped by your output choice.")
        status = "\n\n".join(status_bits)
        if warnings:
            status += "\n\n**Warnings / notes:**\n" + "\n".join(f"- {w}" for w in warnings[:18])
        log = "\n".join(build_log_parts)
        source_zip = _write_zip(project_name, source_map, _source_info(status, log), "source")
        if output_preference in {"JAR + Source", "Source only"} or not compile_ok:
            outputs.append(source_zip)
        if jar_path and output_preference in {"JAR + Source", "JAR only"}:
            outputs.insert(0, jar_path)
        manifest.update({"compiled": compile_ok, "outputs": [Path(p).name for p in outputs], "warnings": warnings, "files": sorted(source_map)})
        return status, outputs, manifest, log

    current = files
    validation_log = ""
    valid = False
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        if artifact_kind == "Shader pack":
            valid, validation_log = validate_shader_pack(current)
        else:
            valid, validation_log = validate_resource_pack(current)
        build_log_parts.append(f"\n=== Validation attempt {attempt}/{MAX_REPAIR_ATTEMPTS} ===\n{validation_log}")
        if valid:
            break
        if attempt < MAX_REPAIR_ATTEMPTS:
            repaired, repair_warnings = _repair_project(
                client, project_name=project_name, artifact_kind=artifact_kind, loader=loader, mc=mc,
                user_prompt=user_prompt, files=_file_map(current), failure_log=validation_log,
            )
            warnings += repair_warnings
            current = repaired

    fmap = _file_map(current)
    if include_readme and "README.md" not in fmap:
        fmap["README.md"] = f"# {project_name}\n\nGenerated by BlockSmith for Minecraft {mc}.\n"
    if artifact_kind == "Shader pack":
        warnings.append("Static shader validation checks file layout, includes, and GLSL syntax; it cannot guarantee final visual appearance without launching Minecraft/Iris/OptiFine.")
    status = f"Generated **{len(fmap)} files** for **Minecraft {mc}**.\n\n" + ("✅ Automated validation passed." if valid else "⚠️ Validation still reports issues after automatic repair attempts; details are shown below.")
    if warnings:
        status += "\n\n**Warnings / notes:**\n" + "\n".join(f"- {w}" for w in warnings[:18])
    log = "\n".join(build_log_parts)
    out_zip = _write_zip(project_name, fmap, _source_info(status, log), "pack")
    outputs.append(out_zip)
    manifest.update({"validated": valid, "outputs": [Path(out_zip).name], "warnings": warnings, "files": sorted(fmap)})
    return status, outputs, manifest, log
