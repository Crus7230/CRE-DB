from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_source_aware_refresh import (
    ACTIVATION_RETRY_DELAYS,
    ActivationError,
    SourceChanged,
    activate_candidate,
    archive_mtime_iso,
    archive_token,
    collector_commands,
    due_domains,
    guarded_backup,
    month_groups,
    prune_owned,
    require_compact_permit_projection,
    recover_existing_candidate,
    refresh_projection,
    safe_partial_permit,
)


SEOUL = ZoneInfo("Asia/Seoul")


def config() -> dict:
    return json.loads((ROOT / "config/source-aware-refresh.json").read_text(encoding="utf-8"))


def recovery_config() -> dict:
    return json.loads(
        (ROOT / "config/molit-baseline-recovery-20260908.json").read_text(
            encoding="utf-8"
        )
    )


def test_due_cadence_is_deterministic_and_independent() -> None:
    cfg = config()
    state = {"domains": {"news": {"lastSuccessfulSlot": "2026-09-08T09:00+09:00"}}}
    now = datetime(2026, 9, 8, 12, 5, tzinfo=SEOUL)  # Tuesday
    assert due_domains(cfg, state, now) == [
        ("news", "2026-09-08T12:00+09:00"),
        ("macro", "2026-09-08T08:00+09:00"),
        ("molit", "2026-09-02T07:30+09:00"),
        ("permits", "2026-09-05T07:30+09:00"),
    ]


def test_news_has_all_six_top_of_hour_slot_identities(tmp_path: Path) -> None:
    cfg = config()
    expected = (6, 9, 12, 15, 18, 21)
    for hour in expected:
        slot = f"2026-09-08T{hour:02d}:00+09:00"
        command = collector_commands("news", tmp_path / "candidate.db", slot, cfg, tmp_path / "report.json")[0]
        assert command[command.index("--collection-slot") + 1] == slot
        assert command[command.index("--lookback-days") + 1] == "2"


def test_weekday_macro_refresh_is_current_year_bounded(tmp_path: Path) -> None:
    cfg = config()
    command = collector_commands(
        "macro", tmp_path / "candidate.db", "2026-09-08T08:00+09:00",
        cfg, tmp_path / "report.json",
    )[0]
    assert command[command.index("--treasury-start-year") + 1] == "2026"
    assert command[command.index("--start-date") + 1] == "2024-09-01"
    assert cfg["domains"]["macro"]["timeoutSeconds"] == 3600


def test_molit_rolling_three_calendar_months_crosses_year() -> None:
    slot = datetime(2026, 1, 7, 7, 30, tzinfo=SEOUL)
    assert month_groups(slot, 3) == [(2025, 11, 12), (2026, 1, 1)]


def test_one_time_molit_recovery_config_rehearses_21_months_without_live_writes(
    tmp_path: Path,
) -> None:
    import scripts.run_source_aware_refresh as module

    recurring = config()
    recovery = recovery_config()
    assert recurring["domains"]["molit"]["correctionMonths"] == 3
    assert recovery["domains"]["molit"]["correctionMonths"] == 21
    assert recovery["archive"] == recurring["archive"]
    assert recovery["lock"] == recurring["lock"]
    assert recovery["publication"]["blockedUntil"] == "2026-10-01"
    for key in ("state", "latestReport", "eventLog", "runReports"):
        assert recovery[key] != recurring[key]

    for key in (
        "state", "latestReport", "eventLog", "runReports", "candidates",
        "backups", "lock",
    ):
        recovery[key] = str(tmp_path / key)
    config_path = tmp_path / "recovery.json"
    config_path.write_text(json.dumps(recovery), encoding="utf-8")
    result = module.orchestrate(
        config_path,
        apply=False,
        allow_live_db=False,
        publish_if_enabled=False,
        selected=["molit"],
        forced_slot="2026-09-08T07:30+09:00",
        now=datetime(2026, 9, 8, 16, 0, tzinfo=SEOUL),
    )
    assert result["status"] == "REHEARSED"
    assert result["due"] == [
        {"domain": "molit", "slot": "2026-09-08T07:30+09:00"}
    ]
    commands = collector_commands(
        "molit", tmp_path / "candidate.db",
        "2026-09-08T07:30+09:00", recovery, tmp_path / "report.json",
    )
    assert len(commands) == 2
    assert [commands[0][commands[0].index("--year") + 1], commands[1][commands[1].index("--year") + 1]] == ["2025", "2026"]
    assert commands[0][commands[0].index("--start-month") + 1] == "1"
    assert commands[1][commands[1].index("--end-month") + 1] == "9"


def test_retention_removes_only_exact_owned_direct_children(tmp_path: Path) -> None:
    for index in range(5):
        path = tmp_path / f"source-aware-2026090{index}-news.db"
        path.write_bytes(str(index).encode())
    unrelated = tmp_path / "user-backup.db"
    unrelated.write_bytes(b"keep")
    child = tmp_path / "nested"
    child.mkdir()
    (child / "source-aware-old.db").write_bytes(b"keep")
    removed = prune_owned(tmp_path, "source-aware-*.db", 3)
    assert len(removed) == 2
    assert unrelated.exists()
    assert (child / "source-aware-old.db").exists()
    assert len(list(tmp_path.glob("source-aware-*.db"))) == 3


def test_default_config_persists_quota_pause() -> None:
    publication = config()["publication"]
    assert publication == {
        "provider": "turso",
        "enabled": True,
        "blockedUntil": "2026-10-01",
        "blockedReason": "QUOTA_READS",
        "bootstrapOnFirstPublish": True,
        "batchRows": 100,
    }


def test_every_domain_uses_a_canonical_publish_dataset() -> None:
    from scripts.incremental_serving_publish import DATASETS

    cfg = config()
    assert {name: item["datasetCode"] for name, item in cfg["domains"].items()} == {
        "news": "DAILY_ARTICLES",
        "macro": "FINANCIAL_MACRO",
        "molit": "MOLIT_TRANSACTIONS",
        "permits": "SEOUL_BUILDING_PERMITS",
    }
    assert all(item["datasetCode"] in DATASETS for item in cfg["domains"].values())


def test_archive_generation_guard_refuses_newer_source(tmp_path: Path) -> None:
    archive = tmp_path / "archive.db"
    candidate = tmp_path / "candidate.db"
    for path, value in ((archive, "old"), (candidate, "candidate")):
        conn = __import__("sqlite3").connect(path)
        conn.execute("CREATE TABLE item(id INTEGER PRIMARY KEY,value TEXT)")
        conn.execute("INSERT INTO item VALUES(1,?)", (value,))
        conn.commit()
        conn.close()
    baseline = archive_token(archive)
    conn = __import__("sqlite3").connect(archive)
    conn.execute("UPDATE item SET value='parallel-newer' WHERE id=1")
    conn.commit()
    conn.close()
    try:
        activate_candidate(candidate, archive, tmp_path / "backups", "news", "run", baseline)
    except SourceChanged:
        pass
    else:
        raise AssertionError("generation mismatch was not rejected")
    conn = __import__("sqlite3").connect(archive)
    assert conn.execute("SELECT value FROM item").fetchone()[0] == "parallel-newer"
    conn.close()
    assert candidate.exists()


def test_activation_retries_transient_windows_permission_error(
    tmp_path: Path, monkeypatch,
) -> None:
    import sqlite3
    import scripts.run_source_aware_refresh as module

    archive = tmp_path / "archive.db"
    candidate = tmp_path / "candidate.db"
    for path, value in ((archive, "old"), (candidate, "new")):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE item(value TEXT)")
        conn.execute("INSERT INTO item VALUES(?)", (value,))
        conn.commit()
        conn.close()
    token = archive_token(archive)
    original_replace = module.os.replace
    attempts = 0

    def transient_replace(source, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(13, "sharing violation", str(target))
        return original_replace(source, target)

    monkeypatch.setattr(module.os, "replace", transient_replace)
    backup = activate_candidate(
        candidate, archive, tmp_path / "backups", "molit", "retry",
        token, retry_delays=(0, 0),
    )
    assert attempts == 3
    assert backup.exists()
    conn = sqlite3.connect(archive)
    assert conn.execute("SELECT value FROM item").fetchone()[0] == "new"
    conn.close()


def test_activation_retry_budget_is_bounded_to_five_seconds() -> None:
    assert sum(ACTIVATION_RETRY_DELAYS) <= 5


def test_activation_failure_exposes_only_safe_stage_errno_and_candidate(
    tmp_path: Path, monkeypatch,
) -> None:
    import sqlite3
    import scripts.run_source_aware_refresh as module

    archive = tmp_path / "archive.db"
    candidate = tmp_path / "candidate.db"
    for path in (archive, candidate):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE item(value TEXT)")
        conn.commit()
        conn.close()

    def blocked_replace(source, target):
        raise PermissionError(13, "secret-bearing OS message", str(target))

    monkeypatch.setattr(module.os, "replace", blocked_replace)
    try:
        activate_candidate(
            candidate, archive, tmp_path / "backups", "molit", "blocked",
            archive_token(archive), retry_delays=(0,),
        )
    except ActivationError as exc:
        fields = exc.report_fields()
    else:
        raise AssertionError("blocked activation unexpectedly succeeded")
    assert fields == {
        "errorCode": "PermissionError",
        "failureStage": "ACTIVATE_REPLACE",
        "candidate": str(candidate),
        "errno": 13,
    }
    assert "secret" not in json.dumps(fields)
    assert candidate.exists()


def test_reviewed_existing_candidate_recovery_is_guarded_and_recollects_nothing(
    tmp_path: Path,
) -> None:
    import sqlite3

    cfg = config()
    cfg["archive"] = str(tmp_path / "archive.db")
    cfg["candidates"] = str(tmp_path / "candidates")
    cfg["backups"] = str(tmp_path / "backups")
    candidate = Path(cfg["candidates"]) / "source-aware-reviewed-molit.candidate.db"
    candidate.parent.mkdir()

    def build(path: Path, value: str, documents: int) -> None:
        conn = sqlite3.connect(path)
        conn.executescript("""
          CREATE TABLE source_documents(id INTEGER PRIMARY KEY);
          CREATE TABLE document_versions(id INTEGER PRIMARY KEY);
          CREATE TABLE collection_runs(id INTEGER PRIMARY KEY);
          CREATE TABLE item(value TEXT);
        """)
        conn.executemany(
            "INSERT INTO source_documents VALUES(?)",
            [(index,) for index in range(documents)],
        )
        conn.execute("INSERT INTO item VALUES(?)", (value,))
        conn.commit()
        conn.close()

    archive = Path(cfg["archive"])
    build(archive, "old", 1)
    build(candidate, "recovered", 2)
    expected_size = archive.stat().st_size
    expected_mtime = archive_mtime_iso(archive)
    rehearsal = recover_existing_candidate(
        cfg, candidate, "molit", expected_archive_size=expected_size,
        expected_archive_mtime=expected_mtime, apply=False,
        allow_live_db=False,
    )
    assert rehearsal["status"] == "RECOVERY_REHEARSED"
    assert rehearsal["publication"] == {
        "status": "PUBLISH_PENDING",
        "reason": "RECOVERY_ACTIVATION_ONLY",
        "remoteAttempted": False,
        "remotePending": True,
    }
    assert candidate.exists()
    result = recover_existing_candidate(
        cfg, candidate, "molit", expected_archive_size=expected_size,
        expected_archive_mtime=expected_mtime, apply=True,
        allow_live_db=True,
    )
    assert result["status"] == "RECOVERED_LOCAL"
    assert result["publication"]["remoteAttempted"] is False
    assert result["validation"]["integrity"] == "ok"
    assert result["validation"]["foreignKeyViolations"] == 0
    conn = sqlite3.connect(archive)
    assert conn.execute("SELECT value FROM item").fetchone()[0] == "recovered"
    conn.close()
    assert not candidate.exists()
    assert (ROOT / result["backup"]).exists() or Path(result["backup"]).exists()


def test_recovery_refuses_changed_archive_before_candidate_validation(tmp_path: Path) -> None:
    import sqlite3

    cfg = config()
    cfg["archive"] = str(tmp_path / "archive.db")
    cfg["candidates"] = str(tmp_path / "candidates")
    cfg["backups"] = str(tmp_path / "backups")
    Path(cfg["candidates"]).mkdir()
    candidate = Path(cfg["candidates"]) / "source-aware-reviewed-molit.candidate.db"
    for path in (Path(cfg["archive"]), candidate):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE item(value TEXT)")
        conn.commit()
        conn.close()
    result = recover_existing_candidate(
        cfg, candidate, "molit",
        expected_archive_size=Path(cfg["archive"]).stat().st_size + 1,
        expected_archive_mtime=archive_mtime_iso(Path(cfg["archive"])),
        apply=True, allow_live_db=True,
    )
    assert result["status"] == "FAILED_LOCAL"
    assert result["errorCode"] == "SOURCE_CHANGED_DURING_RECOVERY"
    assert result["failureStage"] == "RECOVERY_ARCHIVE_GUARD"
    assert candidate.exists()


def test_news_projection_really_runs_on_small_archive_fixture(tmp_path: Path) -> None:
    import sqlite3

    database = tmp_path / "fixture.db"
    conn = sqlite3.connect(database)
    conn.executescript((ROOT / "db/v2/schema.sql").read_text(encoding="utf-8"))
    conn.executescript((ROOT / "db/v2/seed.sql").read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    result = refresh_projection(database, "news")
    assert result["status"] == "READY"
    assert result["articleRows"] == result["detailRows"] == 0
    conn = sqlite3.connect(database)
    assert conn.execute(
        "SELECT source_status_code FROM serving_dataset_freshness WHERE dataset_code='DAILY_ARTICLES'"
    ).fetchone() == ("READY",)
    conn.close()


def test_nonempty_permit_source_cannot_publish_an_empty_compact_mart() -> None:
    try:
        require_compact_permit_projection(
            {"seoulCurrentRows": 12},
            {"permitMonthlyRows": 0},
        )
    except RuntimeError as exc:
        assert "not built" in str(exc)
    else:
        raise AssertionError("empty compact permit mart was accepted")

    require_compact_permit_projection(
        {"seoulCurrentRows": 12},
        {"permitMonthlyRows": 4},
    )


def test_stale_running_permit_snapshot_keeps_committed_resume_pages(tmp_path: Path) -> None:
    import sqlite3

    candidate = tmp_path / "permit.db"
    conn = sqlite3.connect(candidate)
    conn.execute(
        """CREATE TABLE building_permit_snapshots(
             snapshot_id TEXT PRIMARY KEY,source_id TEXT,snapshot_kind TEXT,
             status_code TEXT,last_completed_page INTEGER,started_at TEXT)"""
    )
    conn.execute(
        "INSERT INTO building_permit_snapshots VALUES(?,?,?,?,?,?)",
        (
            "snap-1", "src_seoul_building_permit", "FULL", "RUNNING", 7,
            "2026-09-08T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()
    assert safe_partial_permit(candidate, {}) is True


def test_guarded_backup_rejects_commit_during_copy(tmp_path: Path, monkeypatch) -> None:
    import sqlite3
    import scripts.run_source_aware_refresh as module

    archive = tmp_path / "archive.db"
    candidate = tmp_path / "candidate.db"
    conn = sqlite3.connect(archive)
    conn.execute("CREATE TABLE item(id INTEGER PRIMARY KEY,value TEXT)")
    conn.execute("INSERT INTO item VALUES(1,'old')")
    conn.commit()
    conn.close()
    original = module.sqlite_backup

    def changing_backup(source, target, source_connection=None):
        original(source, target, source_connection)
        writer = sqlite3.connect(source)
        writer.execute("UPDATE item SET value='new' WHERE id=1")
        writer.commit()
        writer.close()

    monkeypatch.setattr(module, "sqlite_backup", changing_backup)
    guard = sqlite3.connect(f"file:{archive.as_posix()}?mode=ro", uri=True)
    try:
        try:
            guarded_backup(archive, candidate, guard)
        except SourceChanged:
            pass
        else:
            raise AssertionError("commit during backup was not rejected")
    finally:
        guard.close()


def test_unknown_publication_failure_is_non_green_but_local_success_is_kept(tmp_path: Path, monkeypatch) -> None:
    import scripts.run_source_aware_refresh as module

    cfg = config()
    for key in ("state", "latestReport", "eventLog", "runReports", "candidates", "backups", "lock"):
        cfg[key] = str(tmp_path / key)
    cfg["archive"] = str(tmp_path / "archive.db")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    Path(cfg["state"]).write_text(
        json.dumps({
            "schemaVersion": 1,
            "domains": {"news": {"lastErrorCode": "COLLECTOR_EXIT_1"}},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "collect_one", lambda *args, **kwargs: {"status": "COLLECTED_LOCAL", "slot": args[1]})
    monkeypatch.setattr(module, "publish_domain", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider down")))
    result = module.orchestrate(
        config_path, apply=True, allow_live_db=True, publish_if_enabled=True,
        selected=["news"], forced_slot="2026-09-08T12:00+09:00",
        now=datetime(2026, 9, 8, 12, 5, tzinfo=SEOUL),
    )
    assert result["status"] == "COLLECTED_LOCAL_WITH_PUBLICATION_FAILURES"
    assert result["hasPublicationFailures"] is True
    assert result["domains"]["news"]["status"] == "COLLECTED_LOCAL"
    assert result["domains"]["news"]["publication"]["status"] == "PUBLISH_FAILED"
    state = json.loads(Path(cfg["state"]).read_text(encoding="utf-8"))
    assert "lastErrorCode" not in state["domains"]["news"]
