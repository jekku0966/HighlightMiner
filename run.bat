@echo off
cd /d "%~dp0"
set "PATH=%CD%;%PATH%"

if not exist .venv\Scripts\python.exe (
  echo Virtual environment not found. Run setup.ps1 first.
  exit /b 1
)

.venv\Scripts\python.exe -m highlightminer ui
