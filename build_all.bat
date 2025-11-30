@echo off
setlocal

echo [INFO] Sprawdzanie srodowiska i instalacja cache...
REM Instalacja ccache pomaga przy kompilacji C (MinGW)
pip install nuitka zstandard ordered-set ccache

echo.
echo [START] Uruchamianie procedury budowania...
echo.

call build_studio.bat
if %ERRORLEVEL% NEQ 0 goto fail

echo.
call build_converter.bat
if %ERRORLEVEL% NEQ 0 goto fail

echo.
echo ========================================================
echo  SUKCES! Calosc zbudowana w: dist\SubtitleStudio
echo ========================================================
pause
exit /b 0

:fail
echo.
echo [BLAD] Proces przerwany z powodu bledow.
pause
exit /b 1