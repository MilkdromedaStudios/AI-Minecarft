from minecraft_builder import _required_file_warnings, _safe_relpath, _sanitize_files


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
