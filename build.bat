@echo off

set DIST_DIR=dist
set APP_DIR=SubtitleStudio
set OLD_DIR=SubtitleStudioOld

REM ---------------------------------------------
REM Obsługa katalogów dist/SubtitleStudio
REM ---------------------------------------------
if exist "%DIST_DIR%\%OLD_DIR%" (
    echo [INFO] Usuwanie starego katalogu "%DIST_DIR%\%OLD_DIR%"...
    rmdir /s /q "%DIST_DIR%\%OLD_DIR%"
)

if exist "%DIST_DIR%\%APP_DIR%" (
    echo [INFO] Zmienianie nazwy katalogu "%DIST_DIR%\%APP_DIR%" na "%OLD_DIR%"...
    ren "%DIST_DIR%\%APP_DIR%" "%OLD_DIR%"
) else (
    echo [INFO] Brak starego katalogu "%DIST_DIR%\%APP_DIR%" - pomijam zmianę nazwy.
)

pyinstaller SubtitleStudio.spec