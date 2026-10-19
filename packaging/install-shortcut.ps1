# Copies the built exe to a per-user folder and adds a Start-menu shortcut.
#   .\install-shortcut.ps1              install
#   .\install-shortcut.ps1 -Uninstall   remove both
#   -DryRun only prints what would happen.
# -InstallDir / -StartMenuDir exist for testing; the defaults are the real places.
param(
    [switch]$Uninstall,
    [switch]$DryRun,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\YouTube Music Cleanup"),
    [string]$StartMenuDir = (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"),
    [string]$Source = (Join-Path (Split-Path -Parent $PSScriptRoot) "dist\YouTube Music Cleanup.exe")
)
$ErrorActionPreference = "Stop"
$name = "YouTube Music Cleanup"
$exe = Join-Path $InstallDir "$name.exe"
$lnk = Join-Path $StartMenuDir "$name.lnk"

if ($Uninstall) {
    Write-Host "Remove shortcut: $lnk"
    Write-Host "Remove folder:   $InstallDir"
    if (-not $DryRun) {
        Remove-Item -LiteralPath $lnk -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    return
}

Write-Host "Copy:     $Source -> $exe"
Write-Host "Shortcut: $lnk (start in $InstallDir)"
if ($DryRun) { return }
if (-not (Test-Path $Source)) { throw "Not built yet: run packaging\build.ps1 first" }

New-Item -ItemType Directory -Force -Path $InstallDir, $StartMenuDir | Out-Null
Copy-Item -LiteralPath $Source -Destination $exe -Force
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = $exe
$s.WorkingDirectory = $InstallDir
$s.Save()
Write-Host "Done."
