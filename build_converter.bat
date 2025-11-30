@echo off
setlocal

set APP_NAME=SubtitleStudio
set CONVERTER_SCRIPT=audio/converter.py
set DIST_DIR=dist

echo [INFO] --- Budowanie Audio Converter ---

REM Sprawdzamy, czy folder docelowy istnieje. Jesli nie - tworzymy go.
if not exist "%DIST_DIR%\%APP_NAME%" mkdir "%DIST_DIR%\%APP_NAME%"

REM Tutaj tez NIE usuwamy folderu 'audio.build' ani 'converter.build' dla zachowania cache.

python -m nuitka ^
    --onefile ^
    --mingw64 ^
    --assume-yes-for-downloads ^
    --include-package=pydub ^
    --output-dir="%DIST_DIR%\%APP_NAME%" ^
    --output-filename="converter.exe" ^
    --show-progress ^
    "%CONVERTER_SCRIPT%"

if %ERRORLEVEL% NEQ 0 (
    echo [BLAD] Kompilacja Convertera zakonczona niepowodzeniem.
    exit /b %ERRORLEVEL%
)

echo [OK] Converter zbudowany.