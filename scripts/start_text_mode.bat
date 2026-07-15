@echo off
cd /d %~dp0..
call venv\Scripts\activate
echo Jarvis METIN MODU (test icin, ses yok)
echo.
python pc-client\jarvis_pc.py --text
pause
