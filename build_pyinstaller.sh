#!/bin/bash
set -e

echo "🚀 Przygotowanie do budowania (PyInstaller)..."

# Sprawdzenie i wybór pliku wykonywalnego Python
if [ -f ".venv/bin/python" ]; then
    echo "✅ Wykryto wirtualne środowisko (.venv). Używam: .venv/bin/python"
    PYTHON_CMD=".venv/bin/python"
elif [ -f "venv/bin/python" ]; then
    echo "✅ Wykryto wirtualne środowisko (venv). Używam: venv/bin/python"
    PYTHON_CMD="venv/bin/python"
else
    echo "⚠️  Nie wykryto lokalnego środowiska wirtualnego (.venv lub venv)."
    echo "ℹ️  Próbuję użyć systemowego polecenia 'python'..."
    PYTHON_CMD="python"
fi


# Uruchomienie skryptu Python
echo "▶️  Uruchamiam build_app.py..."
"$PYTHON_CMD" build_app.py

# Budowanie aplikacji przez PyInstaller
PYINSTALLER_SPEC="SubtitleStudio.spec"
OUTPUT_DIR="build/SubtitleStudio_dir/"
TARGET_DIR="$HOME/Applications/SubtitleStudio/"

echo "▶️  Budowanie aplikacji przez PyInstaller..."
"$PYTHON_CMD" -m PyInstaller "$PYINSTALLER_SPEC"

# Jeśli podano argument 'install', kopiuj do katalogu docelowego
if [ "$1" == "install" ]; then
    echo "📦 Kopiowanie aplikacji do $TARGET_DIR"
    mkdir -p "$TARGET_DIR"
    cp -r "$OUTPUT_DIR"* "$TARGET_DIR"
    echo "✅ Aplikacja została skopiowana do $TARGET_DIR"
else
    echo "ℹ️  Budowanie zakończone. Aby zainstalować, uruchom: ./build_pyinstaller.sh install"
fi
