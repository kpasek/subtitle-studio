#!/bin/bash
set -e

DIST_DIR="dist"
APP_DIR="SubtitleStudio"
OLD_DIR="SubtitleStudioOld"

echo "---------------------------------------------"
echo " Obsługa katalogów $DIST_DIR/$APP_DIR"
echo "---------------------------------------------"

# Usuwanie starego katalogu OLD_DIR
if [ -d "$DIST_DIR/$OLD_DIR" ]; then
    echo "[INFO] Usuwanie starego katalogu '$DIST_DIR/$OLD_DIR'..."
    rm -rf "$DIST_DIR/$OLD_DIR"
fi

# Zmienianie nazwy katalogu APP_DIR na OLD_DIR
if [ -d "$DIST_DIR/$APP_DIR" ]; then
    echo "[INFO] Zmienianie nazwy katalogu '$DIST_DIR/$APP_DIR' na '$OLD_DIR'..."
    mv "$DIST_DIR/$APP_DIR" "$DIST_DIR/$OLD_DIR"
else
    echo "[INFO] Brak starego katalogu '$DIST_DIR/$APP_DIR' - pomijam zmianę nazwy."
fi

# Budowanie aplikacji
echo "[INFO] Uruchamianie PyInstaller..."
pyinstaller SubtitleStudio.spec

echo "[INFO] Budowanie zakończone."
