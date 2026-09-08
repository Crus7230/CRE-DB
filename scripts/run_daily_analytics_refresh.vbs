Option Explicit
Dim sh, fso, scriptDir, command, rc
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
command = Chr(34) & scriptDir & "\run_daily_analytics_refresh.cmd" & Chr(34)
rc = sh.Run(command, 0, True)
If rc = 75 Then rc = 0
WScript.Quit rc
