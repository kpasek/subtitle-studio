#!/usr/bin/env python3
import argparse
import os
import sys
import json
import concurrent.futures
import subprocess
from pathlib import Path
from pydub import AudioSegment


def convert_file(input_file: Path, output_file: Path, speed: float, filters: dict):
    """Konwertuje pojedynczy plik audio do OGG z filtrami FFmpeg."""
    temp_file = output_file.with_suffix(".temp.ogg")
    audio = AudioSegment.from_file(input_file)
    audio.export(temp_file, format="ogg")

    filter_list = []
    order = ["highpass", "lowpass", "deesser", "acompressor", "loudnorm", "alimiter"]
    for f in order:
        conf = filters.get(f)
        if conf and conf.get("enabled", False):
            params = conf.get("params")
            if params:
                filter_list.append(f"{f}={params}")

    filter_str = ",".join(filter_list)
    speed_filter = f"atempo={speed}" if speed != 1.0 else ""
    if filter_str and speed_filter:
        full_chain = f"{filter_str},{speed_filter}"
    elif filter_str:
        full_chain = filter_str
    else:
        full_chain = speed_filter

    cmd = ["ffmpeg", "-i", str(temp_file)]
    if full_chain:
        cmd += ["-af", full_chain, "-c:a", "libvorbis"]
    else:
        cmd += ["-c", "copy"]
    cmd += ["-y", "-loglevel", "error", str(output_file)]

    try:
        subprocess.run(cmd, check=True, text=True, capture_output=True)
        os.remove(temp_file)
        print(f"✅ {input_file.name} → {output_file.name}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Błąd konwersji {input_file.name}: {e.stderr}")
    except Exception as e:
        print(f"❌ Nieoczekiwany błąd {input_file.name}: {e}")


def convert_directory(dir_path: Path, workers: int, speed: float, filters: dict):
    """Konwertuje wszystkie pliki WAV/MP3 w katalogu."""
    ready_dir = dir_path / "ready"
    ready_dir.mkdir(exist_ok=True)
    files = [f for f in dir_path.glob("*.*") if f.suffix.lower() in [".wav", ".mp3"]]

    print(f"Znaleziono {len(files)} plików do konwersji. Użycie {workers} wątków.\n")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for f in files:
            out = ready_dir / (f.stem + ".ogg")
            if out.exists():
                print(f"⚠️  Plik {out.name} już istnieje. Pomijam.")
                continue
            futures.append(executor.submit(convert_file, f, out, speed, filters))
        concurrent.futures.wait(futures)

    print("\n✅ Konwersja zakończona.")


def main():
    parser = argparse.ArgumentParser(description="Niezależny konwerter audio do OGG.")
    parser.add_argument("--path", help="Ścieżka do pliku lub katalogu.")
    parser.add_argument("--workers", type=int, default=4, help="Liczba wątków dla katalogu.")
    parser.add_argument("--speed", type=float, default=1.0, help="Mnożnik prędkości audio.")
    parser.add_argument("--filters", type=str, default="{}", help="JSON z konfiguracją filtrów.")
    args = parser.parse_args()

    print(args)

    path = Path(args.path)
    filters = json.loads(args.filters) if args.filters else {}
    if path.is_file():
        output = path.with_suffix(".ogg")
        convert_file(path, output, args.speed, filters)
    elif path.is_dir():
        convert_directory(path, args.workers, args.speed, filters)
    else:
        print("Błędna ścieżka:", path)
        sys.exit(1)


if __name__ == "__main__":
    main()
