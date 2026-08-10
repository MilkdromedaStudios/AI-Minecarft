from app import _friendly_error_result
from minecraft_builder import _required_file_warnings, _safe_relpath, _sanitize_files
from modeling_builder import _render_textures, validate_model_project


def test_safe_relpath():
    assert _safe_relpath("src/main/Test.java") == "src/main/Test.java"
    assert _safe_relpath("../secret") is None
    assert _safe_relpath("/etc/passwd") == "etc/passwd"


def test_sanitize_files():
    files, warnings = _sanitize_files([
        {"path": "a.txt", "content": "ok"},
        {"path": "../bad.txt", "content": "no"},
        {"path": "a.txt", "content": "duplicate"},
    ])
    assert files == [{"path": "a.txt", "content": "ok"}]
    assert warnings


def test_required_resource_pack():
    warnings = _required_file_warnings("Resource pack", "Vanilla / N/A", {"assets/x.txt"})
    assert any("pack.mcmeta" in w for w in warnings)


def test_model_texture_render_and_validation():
    textures, warnings = _render_textures([
        {
            "path": "assets/demo/textures/item/crystal.png",
            "width": 2,
            "height": 2,
            "pixels": [
                ["#ff0000", "#00ff00"],
                ["#0000ff", "#ffffff80"],
            ],
        }
    ])
    assert not warnings
    assert textures["assets/demo/textures/item/crystal.png"].startswith(b"\x89PNG")

    files = {
        "assets/demo/models/item/crystal.json": """
        {
          "parent": "minecraft:item/generated",
          "textures": {"layer0": "demo:item/crystal"}
        }
        """
    }
    ok, log = validate_model_project(files, textures, "Java block/item model")
    assert ok, log


def test_bbmodel_requires_meta_version():
    files = {"model.bbmodel": '{"elements":[],"outliner":[]}'}
    ok, log = validate_model_project(files, {}, "Blockbench (.bbmodel)")
    assert not ok
    assert "meta.format_version" in log


def test_out_of_credits_error_is_friendly():
    status, outputs, manifest, log = _friendly_error_result(
        "402 Payment Required: insufficient credit balance",
        error_type="HfHubHTTPError",
    )
    assert "Out of Hugging Face inference credits" in status
    assert outputs == []
    assert manifest["error_code"] == "hf_inference_credits_exhausted"
    assert manifest["visitor_oauth"] is True
    assert "402 Payment Required" in log
