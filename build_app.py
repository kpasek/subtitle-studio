import PyInstaller.__main__
import shutil
import os
import sys

def check_environment():
    try:
        import customtkinter
    except ImportError:
        print("❌ BŁĄD: Nie znaleziono modułu 'customtkinter'.")
        print("💡 Rozwiązanie:")
        print("   1. Upewnij się, że aktywowałeś wirtualne środowisko (np. 'source .venv/bin/activate').")
        print("   2. Zainstaluj brakujące pakiety: 'pip install -r requirements.txt'.")
        sys.exit(1)
        
    try:
        import PyInstaller
    except ImportError:
        print("❌ BŁĄD: Nie znaleziono PyInstaller.")
        print("💡 Rozwiązanie: Zainstaluj go komendą 'pip install pyinstaller'.")
        sys.exit(1)

def build():
    check_environment()
    print("🚀 Rozpoczynam budowanie SubtitleStudio...")
    
    # Clean previous build artifacts
    if os.path.exists('build'):
        print("🧹 Czyszczenie katalogu build...")
        shutil.rmtree('build')
    if os.path.exists('dist'):
        print("🧹 Czyszczenie katalogu dist...")
        shutil.rmtree('dist')

    print("📦 Uruchamianie PyInstaller...")
    PyInstaller.__main__.run([
        'SubtitleStudio_dir.spec',
        '--noconfirm',
        '--clean'
    ])
    
    print("✅ Zakończono pomyślnie!")
    print(f"📂 Wynik znajduje się w katalogu: {os.path.abspath('dist/SubtitleStudio')}")

if __name__ == '__main__':
    build()
