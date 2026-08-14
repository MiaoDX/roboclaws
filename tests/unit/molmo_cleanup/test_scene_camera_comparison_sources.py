from __future__ import annotations

from typing import Any

import pytest

from roboclaws.household import scene_camera_capture


class _FakeDistribution:
    def __init__(self, direct_url_text: str | None) -> None:
        self._direct_url_text = direct_url_text

    def read_text(self, name: str) -> str | None:
        assert name == "direct_url.json"
        return self._direct_url_text


def _set_distribution(monkeypatch: pytest.MonkeyPatch, direct_url_text: str | None) -> None:
    monkeypatch.setattr(
        scene_camera_capture.metadata,
        "distribution",
        lambda package: _FakeDistribution(direct_url_text),
    )


def test_official_molmospaces_source_reports_installed_git_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_distribution(
        monkeypatch,
        (
            '{"url":"https://github.com/allenai/molmospaces.git",'
            '"vcs_info":{"vcs":"git","commit_id":"abc123","requested_revision":"main"}}'
        ),
    )

    source = scene_camera_capture._official_molmospaces_source()

    assert source == {
        "package": "molmo-spaces",
        "status": "installed",
        "url": "https://github.com/allenai/molmospaces.git",
        "vcs": "git",
        "commit_id": "abc123",
        "requested_revision": "main",
    }


def test_official_molmospaces_source_reports_missing_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_missing(_package: str) -> Any:
        raise scene_camera_capture.metadata.PackageNotFoundError("molmo-spaces")

    monkeypatch.setattr(scene_camera_capture.metadata, "distribution", raise_missing)

    source = scene_camera_capture._official_molmospaces_source()

    assert source == {
        "package": "molmo-spaces",
        "status": "not_installed",
        "expected_source": "https://github.com/allenai/molmospaces",
    }


@pytest.mark.parametrize("direct_url_text", ["{not-json\n", "[]\n"])
def test_official_molmospaces_source_reports_unreadable_direct_url_metadata(
    monkeypatch: pytest.MonkeyPatch,
    direct_url_text: str,
) -> None:
    _set_distribution(monkeypatch, direct_url_text)

    source = scene_camera_capture._official_molmospaces_source()

    assert source["package"] == "molmo-spaces"
    assert source["status"] == "metadata_unreadable"
    assert source["expected_source"] == "https://github.com/allenai/molmospaces"
    assert "molmo-spaces direct_url.json source" in source["error"]


def test_official_molmospaces_source_reports_missing_direct_url_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_distribution(monkeypatch, None)

    source = scene_camera_capture._official_molmospaces_source()

    assert source == {
        "package": "molmo-spaces",
        "status": "metadata_unavailable",
        "expected_source": "https://github.com/allenai/molmospaces",
    }
