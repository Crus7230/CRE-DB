from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).parents[1]; sys.path.insert(0,str(ROOT))
from scripts.install_daily_analytics_task import build_task_xml, decode_task_xml, task_xml, verify_xml  # noqa: E402


def test_task_xml_is_daily_bounded_and_synchronous() -> None:
    xml=build_task_xml(r"DESKTOP\\user",Path(r"C:\project\run.vbs"),"2026-08-23T06:30:00")
    for token in ("<ScheduleByDay>","<DaysInterval>1</DaysInterval>","<StartWhenAvailable>true</StartWhenAvailable>","<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>","<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>","<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>","<ExecutionTimeLimit>PT30M</ExecutionTimeLimit>","<RestartOnFailure>","wscript.exe"):
        assert token in xml
    assert "InteractiveToken" in xml and "C:\\project\\run.vbs" in xml


def test_launcher_is_apply_explicit_and_wrapper_waits() -> None:
    cmd=(ROOT/"scripts/run_daily_analytics_refresh.cmd").read_text(encoding="utf-8")
    vbs=(ROOT/"scripts/run_daily_analytics_refresh.vbs").read_text(encoding="utf-8")
    assert "--apply" in cmd and "--allow-live-db" in cmd and "--max-attempts 3" in cmd
    assert "run_market_refresh_pipeline.py" in cmd and "--sync-if-enabled" in cmd
    assert "psycopg[binary]" in cmd and "market.db" in cmd
    assert "run_daily_analytics_refresh.py" not in cmd
    assert "sh.Run(command, 0, True)" in vbs and "WScript.Quit rc" in vbs


def test_schtasks_utf8_with_utf16_declaration_preserves_korean_path() -> None:
    wrapper=Path(r"C:\작업\RA 기획추진\run.vbs")
    xml=build_task_xml(r"DESKTOP\user",wrapper,"2026-09-01T06:30:00")
    result=subprocess.CompletedProcess([],0,xml.encode("utf-8"),b"")
    with patch("scripts.install_daily_analytics_task.subprocess.run",return_value=result) as run:
        decoded=task_xml()
    assert decoded==xml
    assert "encoding" not in run.call_args.kwargs and "text" not in run.call_args.kwargs
    assert verify_xml(decoded,wrapper)["verified"]


def test_task_xml_decodes_bom_and_bomless_unicode_variants() -> None:
    wrapper=Path(r"C:\작업\run.vbs")
    xml=build_task_xml(r"DESKTOP\user",wrapper,"2026-09-01T06:30:00")
    for encoding in ("utf-8-sig","utf-16","utf-16-le","utf-16-be"):
        decoded=decode_task_xml(xml.encode(encoding))
        assert decoded==xml
        assert verify_xml(decoded,wrapper)["verified"]


def test_task_xml_decodes_legacy_windows_code_page() -> None:
    wrapper=Path(r"C:\작업\run.vbs")
    xml=build_task_xml(r"DESKTOP\user",wrapper,"2026-09-01T06:30:00")
    # Only Windows supplies the mbcs codec used by schtasks on legacy consoles.
    if sys.platform=="win32":
        assert decode_task_xml(xml.encode("mbcs"))==xml


def test_xml_verification_unescapes_and_normalizes_exact_action_path() -> None:
    wrapper=Path(r"C:\작업 & 자료\run.vbs")
    xml=build_task_xml(r"DESKTOP\user",wrapper,"2026-09-01T06:30:00")
    xml=xml.replace("wscript.exe",r"C:\Windows\System32\WSCRIPT.EXE")
    xml=xml.replace(r"C:\작업 &amp; 자료\run.vbs",r"c:/작업 &amp; 자료/run.vbs")
    assert verify_xml(xml,wrapper)["verified"]


def test_xml_verification_rejects_wrong_path_and_settings_by_name() -> None:
    wrapper=Path(r"C:\project\run.vbs")
    xml=build_task_xml(r"DESKTOP\user",wrapper,"2026-09-01T06:30:00")
    for broken,label in (
        (xml.replace("run.vbs","other.vbs"),"wrapper_path"),
        (xml.replace("<DaysInterval>1</DaysInterval>","<DaysInterval>2</DaysInterval>"),"daily_interval"),
    ):
        try:
            verify_xml(broken,wrapper)
        except RuntimeError as exc:
            assert label in str(exc)
        else:
            raise AssertionError("incorrect task configuration was accepted")
