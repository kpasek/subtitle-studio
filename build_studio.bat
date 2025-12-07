@echo off
echo ========================================================
echo [1/1] Budowanie aplikacji Subtitle Studio (Nuitka)...
echo ========================================================

REM Usuń poprzednie buildy aplikacji, aby uniknąć konfliktów
if exist "dist\SubtitleStudio.exe" del "dist\SubtitleStudio.exe"
set "TEMP_BUILD_DIR=%SystemDrive%\nk_build"

REM Uruchomienie Nuitka
python -m nuitka ^
    --standalone ^
    --onefile ^
    --enable-plugin=tk-inter ^
    --include-data-dir=assets=assets ^
    --windows-icon-from-ico=assets/icon512.ico ^
    --include-package=customtkinter ^
    --include-package=elevenlabs ^
    --include-package=elevenlabs.types ^
    --include-package=google.cloud ^
    --include-package=pydub ^
    --windows-console-mode=disable ^
    --mingw64 ^
    --output-dir="%TEMP_BUILD_DIR%" ^
    -o SubtitleStudio.exe ^
    studio.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [SUKCES] Zbudowano SubtitleStudio.exe w katalogu dist/
) else (
    echo.
    echo [BLAD] Wystapil blad podczas budowania aplikacji.
)
pause