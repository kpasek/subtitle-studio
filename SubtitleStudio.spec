# gui.spec
# Spec file for PyInstaller build with tkinter + pyaudioop
# Run: pyinstaller gui.spec

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# 🔹 Automatycznie zbiera wszystkie moduły z pyaudioop (jeśli jest zainstalowany)
hiddenimports = []
try:
    hiddenimports += collect_submodules('pyaudioop')
except ImportError:
    pass  # w Pythonie <3.13 nie ma pyaudioop

# 🔹 Zbierz dane (np. fonty, pliki konfiguracyjne, assets)
datas = []
datas += collect_data_files('tkinter')  # tkinter resources
datas += collect_data_files('pyaudioop', include_py_files=True)  # jeśli istnieje
datas += [
    ('assets', 'assets'),  # przykładowy katalog zasobów
]

block_cipher = None

a = Analysis(
    ['studio.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports + ['tkinter', 'pyaudioop'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SubtitleStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='SubtitleStudio',
)
