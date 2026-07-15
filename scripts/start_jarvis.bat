@echo off
cd /d %~dp0..

:: Sunucuyu arka planda başlat
start "Jarvis Server" /min cmd /c "call C:\Users\bozca\anaconda3\Scripts\activate.bat jarvis && python -m backend.server"

:: 5 saniye bekle (sunucu hazırlanıyor)
timeout /t 5 /nobreak >nul

:: PC Client'ı arka planda başlat
start "Jarvis Client" /min cmd /c "call C:\Users\bozca\anaconda3\Scripts\activate.bat jarvis && python pc-client\jarvis_pc.py"
