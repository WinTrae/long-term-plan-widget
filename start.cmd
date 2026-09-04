@echo off
setlocal
cd /d "%~dp0"

where pythonw.exe >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer and enable "Add python.exe to PATH".
  pause
  exit /b 1
)

start "" pythonw.exe "%~dp0plan_widget.pyw"
exit /b 0

