@echo off
cd /d %~dp0..
echo =============================================
echo     JARVIS Kurulum Scripti (Windows)
echo =============================================
echo.

:: Python kontrolü
python --version >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python bulunamadi. https://python.org adresinden yukleyin.
    pause
    exit /b 1
)

:: Sanal ortam
echo [1/5] Python sanal ortami olusturuluyor...
python -m venv venv
call venv\Scripts\activate

:: Bagimliliklar
echo [2/5] Python bagimliliklar yukleniyor...
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
venv\Scripts\pip.exe install -r backend\requirements.txt

:: .env dosyasi
if not exist .env (
    echo [3/5] .env dosyasi olusturuluyor...
    copy .env.example .env
    echo.
    echo !!! ONEMLI: .env dosyasini acip GEMINI_API_KEY degerini girin !!!
    echo.
) else (
    echo [3/5] .env dosyasi zaten var, atlanıyor.
)

:: Whisper model indir
echo [4/5] Whisper modeli indiriliyor (ilk seferde biraz surebilir)...
python -c "import whisper; whisper.load_model('base'); print('Whisper hazir!')"

echo [5/5] Kurulum tamamlandi!
echo.
echo Baslangic:
echo   1. .env dosyasina GEMINI_API_KEY ekleyin
echo   2. start_server.bat calistirin
echo   3. start_pc_client.bat calistirin
echo.
pause
