$root = Split-Path $PSScriptRoot -Parent
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Melon.lnk'))
$shortcut.TargetPath = Join-Path $env:WINDIR 'System32/wscript.exe'
$shortcut.Arguments = '"' + (Join-Path $root 'Melon.vbs') + '"'
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'Melon — your work, remembered'
$shortcut.IconLocation = Join-Path $root 'melon.ico'
$shortcut.Save()
