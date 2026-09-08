"""Install and verify the CRE DB daily analytics Windows scheduled task."""
from __future__ import annotations
import argparse
import codecs
import html
import json
import ntpath
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime,timedelta
from pathlib import Path

TASK_NAME=r"\CRE DB\Daily Analytics Refresh"

def build_task_xml(user_id: str, wrapper: Path, start_boundary: str) -> str:
    user=html.escape(user_id); action=html.escape(str(wrapper))
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Daily deterministic CRE keyword and evidence-backed insight refresh.</Description></RegistrationInfo>
  <Triggers><CalendarTrigger><StartBoundary>{start_boundary}</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>false</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>true</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT30M</ExecutionTimeLimit><Priority>7</Priority><RestartOnFailure><Interval>PT5M</Interval><Count>2</Count></RestartOnFailure></Settings>
  <Actions Context="Author"><Exec><Command>wscript.exe</Command><Arguments>"{action}"</Arguments></Exec></Actions>
</Task>'''

def decode_task_xml(output: bytes) -> str:
    # schtasks may emit UTF-8 console bytes while retaining a UTF-16 XML
    # declaration. Decode the actual stream, not the declaration or ANSI ACP.
    if output.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return output.decode("utf-16")
    if output.startswith(codecs.BOM_UTF8):
        return output.decode("utf-8-sig")
    if output.startswith(b"<\x00"):
        return output.decode("utf-16-le")
    if output.startswith(b"\x00<"):
        return output.decode("utf-16-be")
    try:
        return output.decode("utf-8")
    except UnicodeDecodeError:
        return output.decode("mbcs")


def task_xml() -> str:
    run=subprocess.run(["schtasks.exe","/Query","/TN",TASK_NAME,"/XML"],capture_output=True,check=False)
    if run.returncode: raise RuntimeError("scheduled task not found")
    return decode_task_xml(run.stdout)

def verify_xml(xml: str, wrapper: Path) -> dict:
    try:
        task=ET.fromstring(xml)
    except ET.ParseError as exc:
        raise RuntimeError("task verification failed: invalid XML") from exc
    required={
        "daily_interval": task.findtext("./{*}Triggers/{*}CalendarTrigger/{*}ScheduleByDay/{*}DaysInterval")=="1",
        "start_when_available": task.findtext("./{*}Settings/{*}StartWhenAvailable")=="true",
        "ignore_new_instances": task.findtext("./{*}Settings/{*}MultipleInstancesPolicy")=="IgnoreNew",
        "execution_time_limit": task.findtext("./{*}Settings/{*}ExecutionTimeLimit")=="PT30M",
    }
    actions=task.findall("./{*}Actions/{*}Exec")
    script_actions=[action for action in actions if ntpath.basename(
        (action.findtext("{*}Command") or "").strip().strip('"')
    ).casefold()=="wscript.exe"]
    required["wscript_action"]=bool(script_actions)
    expected=ntpath.normcase(ntpath.normpath(str(wrapper)))
    required["wrapper_path"]=any(
        ntpath.normcase(ntpath.normpath((action.findtext("{*}Arguments") or "").strip().strip('"')))==expected
        for action in script_actions
    )
    missing=[name for name,valid in required.items() if not valid]
    if missing: raise RuntimeError("task verification failed: " + ", ".join(missing))
    return {"taskName":TASK_NAME,"verified":True,"settingsChecked":len(required)}

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--install",action="store_true"); parser.add_argument("--status",action="store_true"); parser.add_argument("--run",action="store_true"); parser.add_argument("--time",default="06:30"); args=parser.parse_args()
    root=Path(__file__).parents[1]; wrapper=(root/"scripts/run_daily_analytics_refresh.vbs").resolve()
    if args.status:
        print(json.dumps(verify_xml(task_xml(),wrapper),ensure_ascii=False,indent=2)); return
    if args.run:
        subprocess.run(["schtasks.exe","/Run","/TN",TASK_NAME],check=True); print(json.dumps({"taskName":TASK_NAME,"started":True})); return
    hour,minute=(int(part) for part in args.time.split(":")); start=(datetime.now()+timedelta(days=1)).replace(hour=hour,minute=minute,second=0,microsecond=0)
    user=subprocess.check_output(["whoami.exe"],text=True,encoding="utf-8",errors="replace").strip(); xml=build_task_xml(user,wrapper,start.isoformat(timespec="seconds"))
    if not args.install:
        print(json.dumps({"taskName":TASK_NAME,"mode":"DRY_RUN","user":user,"startBoundary":start.isoformat(timespec="seconds"),"wrapperExists":wrapper.exists()},ensure_ascii=False,indent=2)); return
    with tempfile.NamedTemporaryFile("w",suffix=".xml",encoding="utf-16",delete=False) as handle: handle.write(xml); temp=Path(handle.name)
    try: subprocess.run(["schtasks.exe","/Create","/TN",TASK_NAME,"/XML",str(temp),"/F"],check=True)
    finally: temp.unlink(missing_ok=True)
    print(json.dumps(verify_xml(task_xml(),wrapper),ensure_ascii=False,indent=2))

if __name__=="__main__": main()
