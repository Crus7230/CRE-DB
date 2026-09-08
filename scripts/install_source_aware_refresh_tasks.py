#!/usr/bin/env python
"""Render or explicitly register the source-aware Windows scheduled task.

The task has all requested KST triggers and one shared ``--due`` action.  A
dry run validates the runtime and prints a compact summary; only ``--apply``
calls ``schtasks``.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
DEFAULT_PYTHON = WORKSPACE / ".codex_tmp" / "cre-dashboard-venv" / "Scripts" / "python.exe"
TASK_NAME = r"\CRE DB Board\SourceAwareLocalRefresh"
NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
EXPECTED_BOUNDARIES = (
    "2026-01-01T06:00:00", "2026-01-01T09:00:00", "2026-01-01T12:00:00",
    "2026-01-01T15:00:00", "2026-01-01T18:00:00", "2026-01-01T21:00:00",
    "2026-01-05T08:00:00", "2026-01-07T07:30:00", "2026-01-10T07:30:00",
)


def _element(parent: ET.Element, name: str, text: str | None = None) -> ET.Element:
    child = ET.SubElement(parent, f"{{{NS}}}{name}")
    if text is not None:
        child.text = text
    return child


def build_task_xml(python: Path, *, username: str) -> str:
    ET.register_namespace("", NS)
    task = ET.Element(f"{{{NS}}}Task", {"version": "1.4"})
    registration = _element(task, "RegistrationInfo")
    _element(registration, "Description", "CRE DB Board source-aware local collection and deferred serving publication")
    principals = _element(task, "Principals")
    principal = _element(principals, "Principal")
    principal.set("id", "Author")
    _element(principal, "UserId", username)
    _element(principal, "LogonType", "InteractiveToken")
    _element(principal, "RunLevel", "LeastPrivilege")
    triggers = _element(task, "Triggers")
    for raw in ("06:00", "09:00", "12:00", "15:00", "18:00", "21:00"):
        trigger = _element(triggers, "CalendarTrigger")
        _element(trigger, "StartBoundary", f"2026-01-01T{raw}:00")
        _element(trigger, "Enabled", "true")
        schedule = _element(trigger, "ScheduleByDay")
        _element(schedule, "DaysInterval", "1")
    macro = _element(triggers, "CalendarTrigger")
    _element(macro, "StartBoundary", "2026-01-05T08:00:00")
    _element(macro, "Enabled", "true")
    weekly = _element(macro, "ScheduleByWeek")
    _element(weekly, "WeeksInterval", "1")
    days = _element(weekly, "DaysOfWeek")
    for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
        _element(days, day)
    for boundary, weekday in (("2026-01-07T07:30:00", "Wednesday"), ("2026-01-10T07:30:00", "Saturday")):
        trigger = _element(triggers, "CalendarTrigger")
        _element(trigger, "StartBoundary", boundary)
        _element(trigger, "Enabled", "true")
        schedule = _element(trigger, "ScheduleByWeek")
        _element(schedule, "WeeksInterval", "1")
        day_set = _element(schedule, "DaysOfWeek")
        _element(day_set, weekday)
    settings = _element(task, "Settings")
    _element(settings, "MultipleInstancesPolicy", "IgnoreNew")
    _element(settings, "StartWhenAvailable", "true")
    _element(settings, "AllowStartOnDemand", "true")
    _element(settings, "ExecutionTimeLimit", "PT6H")
    _element(settings, "Enabled", "true")
    actions = _element(task, "Actions")
    actions.set("Context", "Author")
    action = _element(actions, "Exec")
    hidden_python = python.with_name("pythonw.exe")
    _element(action, "Command", str(hidden_python.resolve()))
    script = ROOT / "scripts" / "run_source_aware_refresh.py"
    config = ROOT / "config" / "source-aware-refresh.json"
    _element(action, "Arguments", f'"{script}" --due --apply --allow-live-db --publish-if-enabled --config "{config}"')
    _element(action, "WorkingDirectory", str(ROOT.resolve()))
    return ET.tostring(task, encoding="unicode")


def validate_runtime(python: Path) -> None:
    if not python.is_file():
        raise RuntimeError(f"stable Python runtime is absent: {python}")
    if not python.with_name("pythonw.exe").is_file():
        raise RuntimeError("stable Python runtime has no hidden-window pythonw launcher")
    subprocess.run(
        [str(python), "-c", "import requests,libsql_client,zoneinfo,sqlite3"],
        check=True, capture_output=True, text=True,
    )


def verify_task_xml(xml: str, expected_launcher: Path) -> None:
    root = ET.fromstring(xml)
    ns = {"t": NS}
    boundaries = tuple(node.text or "" for node in root.findall(".//t:StartBoundary", ns))
    if boundaries != EXPECTED_BOUNDARIES:
        raise RuntimeError("registered task trigger readback mismatch")
    if root.findtext(".//t:MultipleInstancesPolicy", namespaces=ns) != "IgnoreNew":
        raise RuntimeError("registered task overlap policy mismatch")
    command = root.findtext(".//t:Command", namespaces=ns)
    if str(Path(command or "").resolve()).casefold() != str(expected_launcher.resolve()).casefold():
        raise RuntimeError("registered task runtime readback mismatch")
    arguments = root.findtext(".//t:Arguments", namespaces=ns) or ""
    if "--due --apply --allow-live-db --publish-if-enabled" not in arguments:
        raise RuntimeError("registered task action readback mismatch")


def _decode_xml(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--task-name", default=TASK_NAME)
    parser.add_argument("--username", default=str(__import__("getpass").getuser()))
    parser.add_argument("--output", type=Path, help="Optionally retain rendered XML")
    parser.add_argument("--apply", action="store_true", help="Register or replace the Windows task")
    args = parser.parse_args()
    validate_runtime(args.python)
    xml = build_task_xml(args.python, username=args.username)
    output = args.output
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if output is None:
        temporary = tempfile.TemporaryDirectory(prefix="cre-source-aware-task-")
        output = Path(temporary.name) / "task.xml"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(xml, encoding="utf-16")
    try:
        if args.apply:
            subprocess.run(["schtasks.exe", "/Create", "/TN", args.task_name, "/XML", str(output), "/F"], check=True)
            readback = subprocess.run(
                ["schtasks.exe", "/Query", "/TN", args.task_name, "/XML"],
                check=True, capture_output=True,
            )
            verify_task_xml(_decode_xml(readback.stdout), args.python.with_name("pythonw.exe"))
            status = "REGISTERED"
        else:
            status = "REHEARSED"
        print(f"{status}: {args.task_name}; triggers=9; runtime={args.python}")
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    main()
