import os
from pathlib import Path
import json
import sys
from typing import Optional, Dict, List, Union
import csv
from app.entity import Line


if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    home = Path.home()
    application_path = home / '.config'

APP_CONFIG = os.path.join(application_path, "subtitle-studio.json")

def get_edits_file_path(loaded_path: Optional[Path]) -> Optional[Path]:
    """Ścieżka dla edycji napisów (clean layer)."""
    if not loaded_path:
        return None
    return loaded_path.with_suffix(".edits.json")


def get_tts_edits_file_path(loaded_path: Optional[Path]) -> Optional[Path]:
    """Ścieżka dla edycji TTS (replace layer)."""
    if not loaded_path:
        return None
    return loaded_path.with_name(loaded_path.stem + ".tts_edits.json")


def load_manual_edits(loaded_path: Optional[Path]) -> Dict[int, str]:
    edits: Dict[int, str] = {}
    path = get_edits_file_path(loaded_path)
    if path and path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                edits = {int(k): v for k, v in data.items()}
        except Exception as e:
            print(f"Błąd edycji (Napisy): {e}")
    return edits


def save_manual_edits(loaded_path: Optional[Path], edits: Dict[int, str]) -> None:
    path = get_edits_file_path(loaded_path)
    if path:
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(edits, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Błąd zapisu edycji (Napisy): {e}")


def load_tts_edits(loaded_path: Optional[Path]) -> Dict[int, str]:
    edits: Dict[int, str] = {}
    path = get_tts_edits_file_path(loaded_path)
    if path and path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                edits = {int(k): v for k, v in data.items()}
        except Exception as e:
            print(f"Błąd edycji (TTS): {e}")
    return edits


def save_tts_edits(loaded_path: Optional[Path], edits: Dict[int, str]) -> None:
    path = get_tts_edits_file_path(loaded_path)
    if path:
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(edits, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Błąd zapisu edycji (TTS): {e}")


def load_subtitle_file(path: str) -> List[Line]:
    """Wczytuje plik napisów.
    - Jeśli CSV: każda linia to obiekt Line (kolumny: original_text,text,tts_text,audio_duration,audio_filename,audio_similarity,audio_status,audio_format)
    - Jeśli TXT (stara wersja): zwraca listę Line z wypełnionymi polami tekstowymi (kompatybilnie)
    """
    p = Path(path)
    if p.suffix.lower() == '.csv':
        out: List[Line] = []
        # Try UTF-8 first, fallback to latin-1 and normalize to UTF-8 on save
        try:
            with open(p, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        dur = round(float(row.get('audio_duration') or 0), 3)
                    except Exception:
                        dur = 0.0
                    l = Line(
                        original_text=row.get('original_text', '') or '',
                        text=row.get('text', '') or '',
                        tts_text=row.get('tts_text', '') or '',
                        audio_duration=dur,
                        audio_filename=row.get('audio_filename', '') or '',
                        audio_similarity=float(row.get('audio_similarity') or 0.0),
                        audio_format=row.get('audio_format', '') or '',
                        audio_transcribed_text=row.get('audio_transcribed_text', '') or ''
                    )
                    out.append(l)
            return out
        except UnicodeDecodeError:
            # fallback: read as latin-1 then return (we don't auto-rewrite here)
            with open(p, 'r', encoding='latin-1', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        dur = round(float(row.get('audio_duration') or 0), 3)
                    except Exception:
                        dur = 0.0
                    # decode fields from latin-1 to python str (already decoded)
                    l = Line(
                        original_text=row.get('original_text', '') or '',
                        text=row.get('text', '') or '',
                        tts_text=row.get('tts_text', '') or '',
                        audio_duration=dur,
                        audio_filename=row.get('audio_filename', '') or '',
                        audio_similarity=float(row.get('audio_similarity') or 0.0),
                        audio_format=row.get('audio_format', '') or '',
                        audio_transcribed_text=row.get('audio_transcribed_text', '') or ''
                    )
                    out.append(l)
            return out
    else:
        with open(p, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        return [Line(original_text=line, text=line, tts_text=line) for line in lines]


def save_lines_to_file(path: str, lines: Union[List[str], List[Line]]) -> None:
    """Zapisuje linie:
    - jeżeli dostaniesz listę Line i rozszerzenie .csv -> zapis w CSV z metadanymi
    - jeżeli dostaniesz listę str lub .txt -> zapis jako zwykły plik tekstowy (stare zachowanie)
    """
    p = Path(path)
    if isinstance(lines, list) and lines and isinstance(lines[0], Line) or p.suffix.lower() == '.csv':
        # Zapis CSV
        with open(p, 'w', encoding='utf-8', newline='') as f:
            fieldnames = ['original_text', 'text', 'tts_text', 'audio_duration', 'audio_filename', 'audio_similarity', 'audio_format', 'audio_transcribed_text']
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for item in lines:
                if isinstance(item, Line):
                    writer.writerow({
                        'original_text': item.original_text,
                        'text': item.text,
                        'tts_text': item.tts_text,
                        'audio_duration': item.audio_duration,
                        'audio_filename': item.audio_filename,
                        'audio_similarity': item.audio_similarity,
                        'audio_format': item.audio_format,
                        'audio_transcribed_text': getattr(item, 'audio_transcribed_text', '')
                    })
                else:
                    writer.writerow({'original_text': item, 'text': item, 'tts_text': item})
    else:
        # plain text save
        with open(p, 'w', encoding='utf-8') as f:
            if isinstance(lines, list) and lines and isinstance(lines[0], Line):
                f.write('\n'.join([l.text for l in lines]))
            else:
                f.write('\n'.join(lines))


def update_line_in_csv(csv_path: str, line_index: int, line: Line) -> None:
    """Aktualizuje pojedynczą linię w pliku CSV (przede wszystkim pola text i tts_text)."""
    p = Path(csv_path)
    if not p.exists() or p.suffix.lower() != '.csv':
        return
    
    try:
        # Odczytaj wszystkie linie, najpierw próbujemy UTF-8, potem fallback latin-1
        all_lines: List[Line] = []
        try:
            with open(p, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        raw_dur = row.get('audio_duration') or row.get('duration') or 0
                        if isinstance(raw_dur, str):
                            raw_dur = raw_dur.replace(',', '.')
                        dur = float(raw_dur or 0)
                    except Exception:
                        dur = 0.0
                    l = Line(
                        original_text=row.get('original_text', '') or '',
                        text=row.get('text', '') or '',
                        tts_text=row.get('tts_text', '') or '',
                        audio_duration=dur,
                        audio_filename=row.get('audio_filename', '') or '',
                        audio_similarity=(lambda v: float(v.replace(',', '.')) if isinstance(v, str) and v else float(v) if v not in (None, '') else 0.0)(row.get('audio_similarity') or row.get('similarity') or 0),
                        audio_format=row.get('audio_format', '') or row.get('ext', '') or '',
                        audio_transcribed_text=row.get('audio_transcribed_text', '') or row.get('transcribed_text', '') or ''
                    )
                    all_lines.append(l)
        except UnicodeDecodeError:
            with open(p, 'r', encoding='latin-1', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        raw_dur = row.get('audio_duration') or row.get('duration') or 0
                        if isinstance(raw_dur, str):
                            raw_dur = raw_dur.replace(',', '.')
                        dur = float(raw_dur or 0)
                    except Exception:
                        dur = 0.0
                    l = Line(
                        original_text=row.get('original_text', '') or '',
                        text=row.get('text', '') or '',
                        tts_text=row.get('tts_text', '') or '',
                        audio_duration=dur,
                        audio_filename=row.get('audio_filename', '') or '',
                        audio_similarity=(lambda v: float(v.replace(',', '.')) if isinstance(v, str) and v else float(v) if v not in (None, '') else 0.0)(row.get('audio_similarity') or row.get('similarity') or 0),
                        audio_format=row.get('audio_format', '') or row.get('ext', '') or '',
                        audio_transcribed_text=row.get('audio_transcribed_text', '') or row.get('transcribed_text', '') or ''
                    )
                    all_lines.append(l)

        # Aktualizuj wybraną linię (jeśli indeks istnieje)
        if 0 <= line_index < len(all_lines):
            all_lines[line_index] = line

        # Zapisz całość powrotem zawsze w UTF-8 (normalizujemy plik)
        with open(p, 'w', encoding='utf-8', newline='') as f:
            fieldnames = ['original_text', 'text', 'tts_text', 'audio_duration', 'audio_filename', 'audio_similarity', 'audio_format', 'audio_transcribed_text']
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for item in all_lines:
                writer.writerow({
                    'original_text': item.original_text,
                    'text': item.text,
                    'tts_text': item.tts_text,
                    'audio_duration': item.audio_duration,
                    'audio_filename': item.audio_filename,
                    'audio_similarity': item.audio_similarity,
                    'audio_format': item.audio_format,
                    'audio_transcribed_text': getattr(item, 'audio_transcribed_text', '')
                })
    except Exception as e:
        print(f"Błąd aktualizacji linii w CSV: {e}")
