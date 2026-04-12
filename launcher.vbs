Dim sDir, oShell
sDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
Set oShell = CreateObject("WScript.Shell")
oShell.Run "cmd /c """ & sDir & "\launch.bat""", 0, False
