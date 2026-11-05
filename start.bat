@echo off
REM DXFtoKRL starten (Windows). Legt beim ersten Start eine Python-Umgebung an.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
.venv\Scripts\pythonw.exe main.py %*
