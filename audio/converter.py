#!/usr/bin/env python3
import argparse
import sys
import json
import concurrent.futures
import subprocess
from pathlib import Path


def convert_file(input_file: Path, output_dir: Path, filters: dict, out_format: str):
    """Konwertuje pojedynczy plik audio do OGG lub MP3 z filtrami FFmpeg."""

    # Ustalanie rozszerzenia i kodeka
    if out_format.lower() == 'mp3':
        codec = ["-c:a", "libmp3lame", "-q:a", "2"]  # V2 ~190kbps VBR
        suffix = ".mp3"
    else:
        codec = ["-c:a", "libvorbis"]
        suffix = ".ogg"

    # Wyjściowy plik (zawsze output1...)
    output_file = output_dir / (input_file.stem + suffix)

    # Budowanie filtrów
    filter_list = []
    order = ["highpass", "lowpass", "deesser", "acompressor", "loudnorm", "alimiter"]
    for f in order:
        conf = filters.get(f)
        if conf and conf.get("enabled", False):
            params = conf.get("params")
            if params:
                filter_list.append(f"{f}={params}")

    filter_str = ",".join(filter_list)

    cmd = ["ffmpeg", "-i", str(input_file)]
    if filter_str:
        cmd += ["-af", filter_str]

    # Dodaj kodek
    cmd += codec

    cmd += ["-y", "-loglevel", "error", str(output_file)]

    try:
        subprocess.run(cmd, check=True, text=True, capture_output=True)
        print(f"✅ {input_file.name} → {output_file.name}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Błąd konwersji {input_file.name}: {e.stderr}")
    except Exception as e:
        print(f"❌ Nieoczekiwany błąd {input_file.name}: {e}")


def convert_directory(dir_path: Path, workers: int, filters: dict, out_format: str):
    """Konwertuje wszystkie pliki WAV/MP3 w katalogu."""
    ready_dir = dir_path.parent / "ready"
    ready_dir.mkdir(exist_ok=True)

    # Pobierz pliki źródłowe
    files = [f for f in dir_path.glob("*.*") if f.suffix.lower() in [".wav", ".mp3", ".ogg"]]
    # Pomiń pliki w ready jeśli glob je złapał (zwykle glob nie wchodzi rekurencyjnie bez rglob)
    files = [f for f in files if "ready" not in f.parts]

    print(f"Znaleziono {len(files)} plików. Format docelowy: {out_format.upper()}. Wątki: {workers}.\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for f in files:
            # Sprawdzamy, czy plik wyjściowy już istnieje
            suffix = ".mp3" if out_format == 'mp3' else ".ogg"
            out_path = ready_dir / (f.stem + suffix)

            if not out_path.exists():
                futures.append(executor.submit(
                    convert_file, f, ready_dir, filters, out_format))
        concurrent.futures.wait(futures)

    print("\n✅ Konwersja zakończona. Naciśnij Enter, aby zamknąć...")
    input()  # Pauza, żeby użytkownik zobaczył wynik w nowym oknie
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Niezależny konwerter audio (Subtitle Studio).")
    parser.add_argument("--path", required=True, help="Ścieżka do katalogu audio.")
    parser.add_argument("--workers", type=int, default=4, help="Liczba wątków.")
    parser.add_argument("--filters", type=str, default="{}", help="JSON z konfiguracją filtrów.")
    parser.add_argument("--format", type=str, default="ogg", help="Format wyjściowy: ogg lub mp3.")

    args = parser.parse_args()
    path = Path(args.path)
    filters = json.loads(args.filters) if args.filters else {}

    if path.is_dir():
        convert_directory(path, args.workers, filters, args.format)
    else:
        print("Podana ścieżka nie jest katalogiem:", path)
        input("Naciśnij Enter...")
        sys.exit(1)


if __name__ == "__main__":
    main()