@echo off
set "DIST_DIR=dist"

echo ========================================================
echo        START BUDOWANIA CALEGO PROJEKTU
echo ========================================================

REM 1. Przygotowanie czystego katalogu dist
if exist "%DIST_DIR%" (
    echo [INFO] Czyszczenie katalogu %DIST_DIR%...
    rmdir /s /q "%DIST_DIR%"
)
mkdir "%DIST_DIR%"

REM 2. Budowanie glownej aplikacji
echo.
echo [INFO] Uruchamianie skryptu build_studio.bat...
REM Uzywamy "call", aby po zakonczeniu skryptu wrocic tutaj
call build_studio.bat
if %ERRORLEVEL% NEQ 0 goto ERROR

REM 3. Budowanie konwertera
echo.
echo [INFO] Uruchamianie skryptu build_converter.bat...
call build_converter.bat
if %ERRORLEVEL% NEQ 0 goto ERROR

echo.
echo ========================================================
echo [GOTOWE] Oba pliki znajduja sie w katalogu: %DIST_DIR%
echo ========================================================
dir "%DIST_DIR%\*.exe"
goto END

:ERROR
echo.
echo [BLAD] Proces budowania zostal przerwany z powodu bledow.

:END
pause