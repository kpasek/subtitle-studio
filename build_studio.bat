@echo off
setlocal

set APP_NAME=SubtitleStudio
set MAIN_SCRIPT=gui.py
set DIST_DIR=dist

echo [INFO] --- Budowanie Subtitle Studio (GUI) ---

REM Czyścimy tylko folder wynikowy (zeby miec pewnosc, ze plik exe jest nowy),
REM ale ZOSTAWIAMY folder roboczy 'gui.build', zeby dzialal cache kompilacji.
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"

REM Flaga --deployment wylacza niektore ostrzezenia i zabezpieczenia przydatne przy developmencie
REM Usunalem --no-pyi-file-info zgodnie z prosba

python -m nuitka ^
    --standalone ^
    --mingw64 ^
    --assume-yes-for-downloads ^
    --windows-disable-console ^
    --windows-icon-from-ico=assets/icon512.ico ^
    --plugin-enable=tk-inter ^
    --include-data-dir=assets=assets ^
    --include-package=customtkinter ^
    --include-package=elevenlabs ^
    --include-package=google.cloud.texttospeech ^
    --include-package=pydub ^
    --include-package=packaging ^
    --output-dir="%DIST_DIR%" ^
    --output-filename="%APP_NAME%.exe" ^
    --show-progress ^
    "%MAIN_SCRIPT%"

if %ERRORLEVEL% NEQ 0 (
    echo [BLAD] Kompilacja GUI zakonczona niepowodzeniem.
    exit /b %ERRORLEVEL%
)

REM Zmieniamy nazwe katalogu z gui.dist na SubtitleStudio
if exist "%DIST_DIR%\gui.dist" (
    move "%DIST_DIR%\gui.dist" "%DIST_DIR%\%APP_NAME%"
)

echo [OK] Subtitle Studio zbudowane.