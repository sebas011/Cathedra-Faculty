@echo off
set "PSModulePath=%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0protect-local-folder.ps1" -Folder "%~dp0.."
if errorlevel 1 (
  echo Folder protection failed. Do not open Cathedra until permissions are corrected.
  pause
  exit /b 1
)
echo This copy is ready for the current Windows account.
pause
