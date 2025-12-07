@echo off
echo ========================================================
echo [1/1] Budowanie converter.exe (Nuitka)...
echo ========================================================

REM Usuń poprzednie buildy konwertera
if exist "dist\converter.exe" del "dist\converter.exe"
set "TEMP_BUILD_DIR=%SystemDrive%\nk_build"

REM Uruchomienie Nuitka
REM Zauważ: audio/converter.py to ścieżka wejściowa
python -m nuitka ^
    --standalone ^
    --onefile ^
    --mingw64 ^
    --include-package=pydub ^
    --output-dir="%TEMP_BUILD_DIR%" ^
    -o converter.exe ^
    audio/converter.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [SUKCES] Zbudowano converter.exe w katalogu dist/
) else (
    echo.
    echo [BLAD] Wystapil blad podczas budowania konwertera.
)
pause