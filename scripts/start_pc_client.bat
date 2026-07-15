@echo off
cd /d %~dp0..
call venv\Scripts\activate
echo Jarvis PC Client baslatiliyor...
echo Wake word: "Jarvis" deyin veya Enter'a basin
echo.
python pc-client\jarvis_pc.py
pause
