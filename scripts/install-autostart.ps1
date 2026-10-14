$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
$launcher = Join-Path $project 'scripts\start-skillforge.ps1'
$shortcutPath = Join-Path $startup 'SkillForge.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'powershell.exe'
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
$shortcut.WorkingDirectory = $project
$shortcut.Description = 'Start SkillForge local services'
$shortcut.Save()
Write-Output "已配置开机自动启动：$shortcutPath"
