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
