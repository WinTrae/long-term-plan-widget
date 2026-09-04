Option Explicit

Dim fso, shell, baseDir, folder, file, scriptPath, pythonw, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set folder = fso.GetFolder(baseDir)
scriptPath = ""

For Each file In folder.Files
    If LCase(fso.GetExtensionName(file.Name)) = "pyw" Then
        scriptPath = file.Path
        Exit For
    End If
Next

If scriptPath = "" Then
    WScript.Quit 2
End If

pythonw = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") _
    & "\Programs\Python\Python312\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw.exe"
End If

command = Chr(34) & pythonw & Chr(34) & " " _
    & Chr(34) & scriptPath & Chr(34)
shell.CurrentDirectory = baseDir
shell.Run command, 0, False
