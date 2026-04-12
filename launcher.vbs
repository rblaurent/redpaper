Dim sScript, oShell, oFSO
sScript = WScript.ScriptFullName
' Read the install path from the .path file next to this script
Set oFSO = CreateObject("Scripting.FileSystemObject")
Dim sPathFile : sPathFile = oFSO.GetParentFolderName(sScript) & "\redpaper.path"
Dim sInstallDir
Set f = oFSO.OpenTextFile(sPathFile, 1)
sInstallDir = Trim(f.ReadLine())
f.Close

Set oShell = CreateObject("WScript.Shell")
' Wait up to 60s for the install drive to become available
Dim i
For i = 1 To 12
    If oFSO.FileExists(sInstallDir & "\main.py") Then Exit For
    WScript.Sleep 5000
Next

If Not oFSO.FileExists(sInstallDir & "\main.py") Then
    WScript.Quit 1
End If

oShell.CurrentDirectory = sInstallDir
oShell.Run "cmd /c python """ & sInstallDir & "\main.py"" >> """ & sInstallDir & "\server.log"" 2>&1", 0, False
