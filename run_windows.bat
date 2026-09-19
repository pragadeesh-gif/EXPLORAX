@echo off
cd /d %~dp0
where py >nul 2>nul
if %errorlevel%==0 (
  start "" http://127.0.0.1:8000
  py app.py
) else (
  start "" http://127.0.0.1:8000
  python app.py
)
pause
