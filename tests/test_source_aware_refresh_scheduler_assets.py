from __future__ import annotations

from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.install_source_aware_refresh_tasks import EXPECTED_BOUNDARIES, NS, build_task_xml, verify_task_xml


def test_task_xml_has_exact_triggers_and_safe_settings(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    xml = build_task_xml(python, username="tester")
    root = ET.fromstring(xml)
    ns = {"t": NS}
    boundaries = [node.text for node in root.findall(".//t:StartBoundary", ns)]
    assert boundaries == list(EXPECTED_BOUNDARIES)
    assert root.findtext(".//t:MultipleInstancesPolicy", namespaces=ns) == "IgnoreNew"
    assert root.findtext(".//t:StartWhenAvailable", namespaces=ns) == "true"
    arguments = root.findtext(".//t:Arguments", namespaces=ns)
    assert "--due --apply --allow-live-db --publish-if-enabled" in arguments
    assert root.findtext(".//t:Command", namespaces=ns).endswith("pythonw.exe")
    verify_task_xml(xml, python.with_name("pythonw.exe"))
