@echo off
echo ========================================================
echo        Subtitle Studio Build Script (PyInstaller)
echo ========================================================

REM --- 1. Konfiguracja Ikony ---
set "ICON_OPT="
if exist "icon.ico" (
    set "ICON_OPT=--icon=icon.ico"
    echo [INFO] Znaleziono ikone: icon.ico
) else (
    if exist "icon.png" (
        set "ICON_OPT=--icon=icon.png"
        echo [INFO] Znaleziono ikone: icon.png
    ) else (
        echo [WARN] Nie znaleziono icon.ico ani icon.png. Aplikacja bedzie miec domyslna ikone.
    )
)

REM --- 2. Czyszczenie poprzednich buildow ---
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

REM --- 3. Budowanie Converter.exe (Tryb konsolowy) ---
echo.
echo [1/2] Budowanie converter.exe...
pyinstaller --noconfirm --onefile --console --name "converter" ^
    --hidden-import="pydub" ^
    audio/converter.py

if %ERRORLEVEL% NEQ 0 (
    echo [BLAD] Nie udalo sie zbudowac converter.exe
    pause
    exit /b %ERRORLEVEL%
)

REM --- 4. Budowanie SubtitleStudio.exe (Tryb okienkowy) ---
echo.
echo [2/2] Budowanie Subtitle Studio...
REM Uzywamy --collect-all dla customtkinter, aby pobrac motywy i pliki json
pyinstaller --noconfirm --onefile --windowed --name "SubtitleStudio" %ICON_OPT% ^
    --add-data "assets;assets" ^
    --collect-all "customtkinter" ^
    --hidden-import="elevenlabs" ^
    --hidden-import="google.cloud.texttospeech" ^
    --hidden-import="pydub" ^
    gui.py

if %ERRORLEVEL% NEQ 0 (
    echo [BLAD] Nie udalo sie zbudowac aplikacji.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ========================================================
echo [SUKCES] Zakonczono. Pliki znajduja sie w folderze dist/
echo ========================================================
echo.
dir "dist\*.exe"
pause