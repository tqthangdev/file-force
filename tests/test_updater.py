from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.updater import apply as apply_mod
from app.core.updater import verifier
from app.core.updater.checker import (
    ReleaseAsset,
    UpdateError,
    UpdateInfo,
    check_for_update,
)
from app.core.updater.version import (
    display_version,
    is_newer,
    parse_version,
    read_current_version,
)

# --------------------------------------------------------------- version logic
def test_parse_version_handles_prefixes_and_suffixes():
    assert parse_version("1.0.2") == (1, 0, 2)
    assert parse_version("v1.0.2") == (1, 0, 2)
    assert parse_version("v1.0.2-beta") == (1, 0, 2)
    assert parse_version("") == ()
    assert parse_version("nonsense") == ()


def test_is_newer_compares_numerically_not_as_text():
    assert is_newer("v1.0.10", "1.0.9") is True
    assert is_newer("1.0.0", "1.0.0") is False
    assert is_newer("1.0.0", "1.0.1") is False
    assert is_newer("", "1.0.0") is False
    assert is_newer("1.0.0", "") is False


def test_display_version_has_exactly_one_v():
    assert display_version("1.2.3") == "v1.2.3"
    assert display_version("v1.2.3") == "v1.2.3"
    assert display_version("VV1.2.3") == "v1.2.3"
    assert display_version("") == "?"


def test_read_current_version_reads_the_project_version_file():
    # Tests run from the source checkout, so version.json is the repo's.
    version = read_current_version()
    assert version and parse_version(version)


# ---------------------------------------------------------------------- checker
class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _release_payload(tag: str, names: list[str]) -> dict:
    return {
        "tag_name": tag,
        "body": "## What's new\n\n* something\n",
        "assets": [
            {"name": n, "browser_download_url": f"https://example/{n}", "size": 10}
            for n in names
        ],
    }


def test_check_for_update_parses_a_release(monkeypatch):
    payload = _release_payload(
        "v9.9.9", ["FileForge-linux.zip", "FileForge-windows.zip"]
    )
    monkeypatch.setattr(
        "app.core.updater.checker.requests.get",
        lambda *a, **k: _FakeResponse(200, payload),
    )

    info = check_for_update()

    assert info.latest == "v9.9.9"
    assert info.available is True
    assert len(info.assets) == 2
    assert info.asset_for_platform() is not None
    assert info.asset_for_platform().name in (
        "FileForge-linux.zip",
        "FileForge-windows.zip",
    )
    assert "something" in info.notes


def test_check_for_update_reports_missing_release(monkeypatch):
    monkeypatch.setattr(
        "app.core.updater.checker.requests.get",
        lambda *a, **k: _FakeResponse(404),
    )
    with pytest.raises(UpdateError):
        check_for_update()


def test_check_for_update_reports_network_errors(monkeypatch):
    import requests

    def boom(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("app.core.updater.checker.requests.get", boom)
    with pytest.raises(UpdateError):
        check_for_update()


def test_asset_for_platform_ignores_non_zip_assets(tmp_path):
    info = UpdateInfo(
        current="1.0.0",
        latest="v2.0.0",
        assets=[
            ReleaseAsset(name="FileForge-linux.tar.gz", url="u"),
            ReleaseAsset(name="notes.txt", url="u"),
        ],
    )
    assert info.asset_for_platform() is None


# --------------------------------------------------------------------- verifier
def _make_package(root: Path, version: str, entry: str = "FileForge") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "_internal").mkdir(exist_ok=True)
    (root / "_internal" / "version.json").write_text(
        json.dumps({"version": version}), encoding="utf-8"
    )
    (root / entry).write_text("binary", encoding="utf-8")
    return root


def test_sha256_and_expected_digest(tmp_path):
    target = tmp_path / "file.bin"
    target.write_bytes(b"hello")
    digest = verifier.sha256_of(target)
    assert len(digest) == 64

    assert verifier.expected_sha256(ReleaseAsset("a", "u", digest=f"sha256:{digest}")) == digest
    assert verifier.expected_sha256(ReleaseAsset("a", "u")) == ""
    # No digest published: nothing to compare against, so it passes.
    assert verifier.verify_download(target, ReleaseAsset("a", "u")) is True
    assert verifier.verify_download(target, ReleaseAsset("a", "u", digest="sha256:00")) is False


def test_validate_package_accepts_a_nested_app_folder(tmp_path):
    package = _make_package(tmp_path / "extracted" / "FileForge", "1.2.3")

    root = verifier.validate_package(tmp_path / "extracted", "v1.2.3")

    assert root == package


def test_validate_package_rejects_wrong_version_and_missing_entry(tmp_path):
    _make_package(tmp_path / "a" / "FileForge", "1.2.3")
    assert verifier.validate_package(tmp_path / "a", "9.9.9") is None

    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "version.json").write_text('{"version": "1.0.0"}', encoding="utf-8")
    assert verifier.validate_package(tmp_path / "b", "1.0.0") is None


def test_version_file_finds_bundled_and_top_level(tmp_path):
    top = _make_package(tmp_path / "top", "1.0.0")
    (top / "version.json").write_text('{"version": "1.0.0"}', encoding="utf-8")
    assert verifier.version_file(top) == top / "version.json"

    nested = _make_package(tmp_path / "nested", "1.0.0")
    assert verifier.version_file(nested) == nested / "_internal" / "version.json"


# ------------------------------------------------------------------------ apply
def test_replace_skips_the_update_folder(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "app.txt").write_text("new", encoding="utf-8")
    (source / ".update").mkdir()
    (source / ".update" / "junk").write_text("x", encoding="utf-8")

    moved: list = []
    apply_mod._replace(source, target, target / ".update" / "backup", moved)

    assert (target / "app.txt").read_text(encoding="utf-8") == "new"
    assert not (target / ".update" / "junk").exists()


def test_apply_package_rolls_back_when_verification_fails(tmp_path):
    target = tmp_path / "install"
    target.mkdir()
    (target / "FileForge").write_text("old", encoding="utf-8")
    (target / "version.json").write_text('{"version": "1.0.0"}', encoding="utf-8")

    # Staged build has no version.json, so verification fails after the swap.
    source = tmp_path / "staged"
    source.mkdir()
    (source / "FileForge").write_text("new", encoding="utf-8")

    assert apply_mod.apply_package(source, target, "2.0.0") is False
    assert (target / "FileForge").read_text(encoding="utf-8") == "old"
    assert (target / "version.json").read_text(encoding="utf-8") == '{"version": "1.0.0"}'


def test_apply_package_installs_and_keeps_no_backup(tmp_path):
    target = tmp_path / "install"
    _make_package(target, "1.0.0")
    source = tmp_path / "staged"
    _make_package(source, "2.0.0")

    assert apply_mod.apply_package(source, target, "v2.0.0") is True
    assert json.loads(
        (target / "_internal" / "version.json").read_text(encoding="utf-8")
    )["version"] == "2.0.0"
    assert not (target / ".update" / "backup").exists()


def test_staging_root_is_the_version_folder(tmp_path):
    root = tmp_path / ".update" / "2.0.0" / "extracted" / "FileForge"
    root.mkdir(parents=True)
    assert apply_mod._staging_root(root) == tmp_path / ".update" / "2.0.0"
