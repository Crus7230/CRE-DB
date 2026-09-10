import json
from pathlib import Path

import pytest

from scripts import publish_compact_dashboard_supabase as publisher


def _delta_manifest() -> dict:
    return {
        "schemaVersion": publisher.EXPECTED_SCHEMA_VERSION,
        "datasetVersion": "cre-20260910T000000Z-aaaaaaaaaaaa",
        "sourceManifestSha256": "a" * 64,
        "tables": {table: {} for table in publisher.LOAD_ORDER},
        "stableTableHashes": {table: "b" * 64 for table in publisher.LOAD_ORDER},
        "delta": {
            "baseDatasetVersion": "cre-20260910T000000Z-bbbbbbbbbbbb",
            "baseSourceManifestSha256": "c" * 64,
            "changedTables": ["market_pulse"],
            "requiredServerCloneTables": list(publisher.DELTA_SERVER_CLONE_TABLES),
        },
    }


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return package


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, row):
        self.row = row

    def execute(self, _sql):
        return _Result(self.row)


def _guard(manifest: dict, active_row: tuple[str, str], **overrides):
    arguments = {
        "reuse_source": manifest["delta"]["baseDatasetVersion"],
        "reused_tables": publisher.DELTA_SERVER_CLONE_TABLES,
        "copied_tables": publisher.DELTA_CHANGED_TABLES,
        "target_exists": False,
    }
    arguments.update(overrides)
    return publisher._enforce_delta_publish_guard(
        _Connection(active_row), manifest, **arguments
    )


def test_read_manifest_accepts_only_the_exact_delta_shape(tmp_path: Path) -> None:
    manifest = _delta_manifest()
    assert publisher.read_manifest(_write_manifest(tmp_path, manifest))["delta"] == manifest["delta"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("changedTables", ["articles"], "changed-table set"),
        ("requiredServerCloneTables", ["articles"], "server-clone table set"),
        ("baseDatasetVersion", "invalid", "base dataset version"),
        ("baseSourceManifestSha256", "invalid", "base manifest hash"),
    ],
)
def test_read_manifest_rejects_delta_shape_drift(
    tmp_path: Path, field: str, value, message: str
) -> None:
    manifest = _delta_manifest()
    manifest["delta"][field] = value

    with pytest.raises(publisher.CompactPublishError, match=message):
        publisher.read_manifest(_write_manifest(tmp_path, manifest))


def test_delta_guard_accepts_exact_active_base_and_retry_plan() -> None:
    manifest = _delta_manifest()
    active = (
        manifest["delta"]["baseDatasetVersion"],
        manifest["delta"]["baseSourceManifestSha256"],
    )

    result = _guard(manifest, active, target_exists=True)

    assert result == {
        "validated": True,
        "baseDatasetVersion": active[0],
        "baseSourceManifestSha256": active[1],
        "serverCloneTables": list(publisher.DELTA_SERVER_CLONE_TABLES),
        "clientCopyTables": ["market_pulse"],
        "targetAlreadyExisted": True,
    }


def test_delta_guard_rejects_changed_active_version() -> None:
    manifest = _delta_manifest()
    with pytest.raises(publisher.CompactPublishError, match="no longer active"):
        _guard(
            manifest,
            (
                "cre-20260910T000000Z-dddddddddddd",
                manifest["delta"]["baseSourceManifestSha256"],
            ),
        )


def test_delta_guard_rejects_changed_active_manifest_hash() -> None:
    manifest = _delta_manifest()
    with pytest.raises(publisher.CompactPublishError, match="manifest hash changed"):
        _guard(
            manifest,
            (manifest["delta"]["baseDatasetVersion"], "d" * 64),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"reused_tables": publisher.DELTA_SERVER_CLONE_TABLES[:-1]},
        {"copied_tables": ("articles", "market_pulse")},
        {"reuse_source": "cre-20260910T000000Z-dddddddddddd"},
    ],
)
def test_delta_guard_rejects_copy_or_clone_plan_drift(overrides: dict) -> None:
    manifest = _delta_manifest()
    active = (
        manifest["delta"]["baseDatasetVersion"],
        manifest["delta"]["baseSourceManifestSha256"],
    )
    with pytest.raises(publisher.CompactPublishError, match="plan drifted|clone source"):
        _guard(manifest, active, **overrides)


def test_delta_guard_runs_before_dataset_insert() -> None:
    source = Path(publisher.__file__).read_text(encoding="utf-8")
    publish_body = source[source.index("def publish_package("):source.index("def inspect_prune_candidate(")]

    assert publish_body.index("delta_guard = _enforce_delta_publish_guard(") < publish_body.index(
        "INSERT INTO cre_system.dataset_versions("
    )


def test_delta_publication_requires_preserved_auth_before_local_auth_read(
    monkeypatch, tmp_path: Path
) -> None:
    manifest = _delta_manifest()
    monkeypatch.setattr(publisher, "read_manifest", lambda _package: manifest)
    monkeypatch.setattr(publisher, "verify_package", lambda _package: {"verified": True})
    monkeypatch.setattr(
        publisher,
        "read_auth_subjects",
        lambda _path: (_ for _ in ()).throw(AssertionError("local auth read attempted")),
    )

    with pytest.raises(publisher.CompactPublishError, match="preserved authorization"):
        publisher.publish_package(
            "unused",
            tmp_path,
            tmp_path / "local-access.db",
            activate=True,
            seed_auth=True,
        )


def test_publish_cli_wires_preserve_auth_and_capacity_guard(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    calls: list[dict] = []
    manifest = _delta_manifest()
    monkeypatch.setattr(
        publisher,
        "target_connection_info",
        lambda *_args, **_kwargs: ("dsn", {"targetRef": "r" * 20}),
    )

    def fake_publish(_dsn, package, auth_db, **kwargs):
        calls.append({"package": package, "authDb": auth_db, **kwargs})
        return {"datasetVersion": "cre-20260910T000000Z-aaaaaaaaaaaa"}

    monkeypatch.setattr(publisher, "publish_package", fake_publish)
    monkeypatch.setattr(publisher, "read_manifest", lambda _package: manifest)
    monkeypatch.setattr(
        publisher,
        "verify_active_publication",
        lambda _dsn, exact_manifest: (
            calls.append({"readbackManifest": exact_manifest})
            or {"verified": True, "verificationMode": "post-commit-manifest-and-count-readback"}
        ),
    )
    monkeypatch.setattr(
        publisher,
        "verify_remote",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("preserve-auth path called write-capable legacy verifier")
        ),
    )

    assert publisher.main([
        "publish",
        "--env", str(tmp_path / "personal.env"),
        "--target-ref", "r" * 20,
        "--pooler-host", "aws-0-region.pooler.supabase.com",
        "--package", str(tmp_path / "package"),
        "--auth-db", str(tmp_path / "local-access.db"),
        "--apply",
        "--activate",
        "--preserve-auth",
        "--max-database-bytes", "450000000",
    ]) == 0

    assert calls == [{
        "package": tmp_path / "package",
        "authDb": tmp_path / "local-access.db",
        "activate": True,
        "max_database_bytes": 450_000_000,
        "seed_auth": False,
    }, {"readbackManifest": manifest}]
    assert json.loads(capsys.readouterr().out)["verification"]["verified"] is True
