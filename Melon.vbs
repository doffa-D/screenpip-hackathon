Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
python = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(python) Then
  MsgBox "Set up Melon using README.md first.", 16, "Melon"
Else
  shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & root & "\desktop_app.py" & Chr(34), 0, False
End If
