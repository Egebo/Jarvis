@echo off
cd /d %~dp0..
call venv\Scripts\activate
echo Jarvis sunucusu baslatiliyor...
echo Adres: ws://localhost:8765
echo.
python -m backend.server
pause
