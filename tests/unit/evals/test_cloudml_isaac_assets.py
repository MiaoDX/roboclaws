from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from roboclaws.evals import cloudml_content_store, cloudml_isaac_assets


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_archive(tmp_path: Path, *, commit: str) -> Path:
    path = tmp_path / "code.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        payload = f"{commit}\n".encode()
        info = tarfile.TarInfo("roboclaws.git/.roboclaws_code_commit")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    Path(f"{path}.sha256").write_text(f"{_sha256(path)}  {path.name}\n", encoding="utf-8")
    return path


def _contract(tmp_path: Path, *, root: str) -> Path:
    payload = {
        "schema": cloudml_isaac_assets.CONTRACT_SCHEMA,
        "asset_groups": {
            "generated-smoke": {
                "stages": ["A"],
                "roots": [],
                "generated_only": True,
                "maximum_archive_bytes": 10000,
            },
            "b1-navigation": {
                "stages": ["B"],
                "roots": [root],
                "generated_only": False,
                "maximum_archive_bytes": 10000,
            },
        },
        "stages": {
            "A": {"asset_group": "generated-smoke"},
            "B": {"asset_group": "b1-navigation"},
        },
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_isaac_asset_staging_is_deterministic_and_uses_content_manifest_v2(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    asset = repo / "assets" / "b1"
    asset.mkdir(parents=True)
    (asset / "scene.usda").write_text("@./mesh.usd@\n", encoding="utf-8")
    (asset / "mesh.usd").write_text("#usda 1.0\n", encoding="utf-8")
    contract = _contract(tmp_path, root="assets/b1")
    code = _code_archive(tmp_path, commit="a" * 40)

    first = cloudml_isaac_assets.prepare_stage(
        repo_root=repo,
        contract_path=contract,
        stage_id="B",
        output_dir=tmp_path / "first",
        code_archive=code,
        code_commit="a" * 40,
    )
    second = cloudml_isaac_assets.prepare_stage(
        repo_root=repo,
        contract_path=contract,
        stage_id="B",
        output_dir=tmp_path / "second",
        code_archive=code,
        code_commit="a" * 40,
    )

    first_payload = json.loads(first.read_text(encoding="utf-8"))
    second_payload = json.loads(second.read_text(encoding="utf-8"))
    first_archive = Path(first_payload["staged_assets"]["archive"]["local_path"])
    second_archive = Path(second_payload["staged_assets"]["archive"]["local_path"])
    assert _sha256(first_archive) == _sha256(second_archive)
    assert first_payload["schema"] == cloudml_content_store.MANIFEST_SCHEMA
    assert first_payload["isaac"]["asset_group"] == "b1-navigation"
    assert [item["path"] for item in first_payload["isaac"]["files"]] == [
        "assets/b1/mesh.usd",
        "assets/b1/scene.usda",
    ]
    with tarfile.open(first_archive, "r:gz") as archive:
        assert archive.getnames() == [
            "roboclaws/assets/b1/mesh.usd",
            "roboclaws/assets/b1/scene.usda",
        ]
    assert cloudml_content_store.load_identity(first)["asset_archive_sha256"] == _sha256(
        first_archive
    )


def test_generated_smoke_archive_contains_no_b1_assets(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = cloudml_isaac_assets.prepare_stage(
        repo_root=repo,
        contract_path=_contract(tmp_path, root="unused"),
        stage_id="A",
        output_dir=tmp_path / "stage-a",
        code_archive=_code_archive(tmp_path, commit="b" * 40),
        code_commit="b" * 40,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["isaac"]["roots"] == []
    assert payload["isaac"]["files"] == []
    with tarfile.open(payload["staged_assets"]["archive"]["local_path"], "r:gz") as archive:
        assert archive.getnames() == ["roboclaws/isaac/generated-smoke.json"]


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("@/home/operator/assets/mesh.usd@\n", "absolute workstation reference"),
        ('{"source": "file:///Users/operator/map.json"}\n', "absolute workstation reference"),
    ],
)
def test_isaac_asset_staging_rejects_absolute_references(
    tmp_path: Path, content: str, match: str
) -> None:
    repo = tmp_path / "repo"
    asset = repo / "assets" / "b1"
    asset.mkdir(parents=True)
    (asset / "scene.usda").write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        cloudml_isaac_assets.prepare_stage(
            repo_root=repo,
            contract_path=_contract(tmp_path, root="assets/b1"),
            stage_id="B",
            output_dir=tmp_path / "stage",
            code_archive=_code_archive(tmp_path, commit="c" * 40),
            code_commit="c" * 40,
        )


def test_isaac_asset_staging_rejects_symlinks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    asset = repo / "assets" / "b1"
    asset.mkdir(parents=True)
    outside = tmp_path / "private.usd"
    outside.write_text("private\n", encoding="utf-8")
    (asset / "private.usd").symlink_to(outside)

    with pytest.raises(ValueError, match="contains a symlink"):
        cloudml_isaac_assets.prepare_stage(
            repo_root=repo,
            contract_path=_contract(tmp_path, root="assets/b1"),
            stage_id="B",
            output_dir=tmp_path / "stage",
            code_archive=_code_archive(tmp_path, commit="d" * 40),
            code_commit="d" * 40,
        )
