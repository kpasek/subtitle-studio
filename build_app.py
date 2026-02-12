import PyInstaller.__main__
import shutil
import os
import sys

def build():
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
