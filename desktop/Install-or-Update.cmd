@echo off
setlocal
set "PSModulePath=%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Office.ps1" -PackageFolder "%~dp0."
if errorlevel 1 (
  echo.
  echo Cathedra was not installed. Read the message above before trying again.
  pause
  exit /b 1
)
echo.
echo Installation complete. Use the Cathedra Faculty desktop shortcut next time.
pause
exit /b 0
