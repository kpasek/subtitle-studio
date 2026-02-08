import os
from pathlib import Path
import json
import sys
from typing import Optional, Dict, List, Union, Tuple
import csv
import uuid

from app.entity import Line


if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    home = Path.home()
    application_path = home / '.config'

APP_CONFIG = os.path.join(application_path, "subtitle-studio.json")


def get_edits_file_path(loaded_path: Optional[Path]) -> Optional[Path]:
    """Sciezka dla edycji napisow (clean layer)."""
    if not loaded_path:
        return None
    return loaded_path.with_suffix(".edits.json")


def get_tts_edits_file_path(loaded_path: Optional[Path]) -> Optional[Path]:
    """Sciezka dla edycji TTS (replace layer)."""
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
            print(f"Blad edycji (Napisy): {e}")
    return edits


def save_manual_edits(loaded_path: Optional[Path], edits: Dict[int, str]) -> None:
    path = get_edits_file_path(loaded_path)
    if path:
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(edits, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Blad zapisu edycji (Napisy): {e}")


def load_tts_edits(loaded_path: Optional[Path]) -> Dict[int, str]:
    edits: Dict[int, str] = {}
    path = get_tts_edits_file_path(loaded_path)
    if path and path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                edits = {int(k): v for k, v in data.items()}
        except Exception as e:
            print(f"Blad edycji (TTS): {e}")
    return edits


def save_tts_edits(loaded_path: Optional[Path], edits: Dict[int, str]) -> None:
    path = get_tts_edits_file_path(loaded_path)
    if path:
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(edits, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Blad zapisu edycji (TTS): {e}")


def _extract_uid_component(value: Optional[str]) -> Optional[str]:
    """Wyodrębnia sam identyfikator z nazwy audio lub zapisanej UID."""
    if not value:
        return None
    base = Path(value).stem
    if '(' in base and ')' in base:
        start = base.index('(') + 1
        end = base.find(')', start)
        if end > start:
            candidate = base[start:end].strip()
            if candidate:
                return candidate
    if base.startswith('output1 '):
        candidate = base[8:].strip()
        if candidate:
            return candidate
    return base or None


def _cleanup_uid_field(raw_uid: Optional[str]) -> str:
    """Czyści UID z prefiksów typu output1 i przycina spacje."""
    candidate = (raw_uid or '').strip()
    normalized = _extract_uid_component(candidate)
    return normalized or candidate


def _normalize_text_fields(line: Line) -> Tuple[str, str]:
    """Zwraca wartości `text` i `tts_text`, pomijając duplikaty względem oryginału."""
    original = line.original_text or ''
    text_value = line.text or ''
    text_for_csv = text_value if text_value and text_value != original else ''
    base_text = text_for_csv or original
    tts_value = line.tts_text or ''
    tts_for_csv = tts_value if tts_value and tts_value != base_text else ''
    return text_for_csv, tts_for_csv


def load_subtitle_file(path: str, audio_dir: Optional[Path] = None) -> List[Line]:
    """Wczytuje plik napisow.
    - CSV: wiersze jako Line z metadanymi, w tym uid
    - TXT (stara wersja): Line z uid zgodnym z plikami audio, jesli istnieja
    """
    p = Path(path)

    def _ensure_uid(value: str, idx: int, audio_dir_path: Optional[Path], audio_filename: str) -> str:
        """Inteligentna rezolucja UID:
        1. Jeśli już podany - zwróć (po oczyszczeniu)
        2. Jeśli nazwa audio zawiera UID - wyodrębnij
        3. Jeśli plik istnieje w audio_dir - użyj numeru linii
        4. Wygeneruj nowy UUID
        """
        normalized_value = _cleanup_uid_field(value)
        if normalized_value:
            return normalized_value

        inferred = _extract_uid_component(audio_filename)
        if inferred:
            return inferred

        if audio_dir_path and audio_dir_path.is_dir():
            pattern_candidates = [f"output1 ({idx})", f"output1({idx})", f"output1 {idx}", str(idx)]
            for pattern in pattern_candidates:
                for ext in ['.wav', '.mp3', '.ogg']:
                    candidate = audio_dir_path / f"{pattern}{ext}"
                    if candidate.exists():
                        return str(idx)

        return uuid.uuid4().hex[:8]

    if p.suffix.lower() == '.csv':
        out: List[Line] = []
        try:
            with open(p, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                row_count = 0
                for row in reader:
                    row_count += 1
                    try:
                        dur = round(float(row.get('audio_duration') or 0), 3)
                    except Exception:
                        dur = 0.0
                    transcribed = row.get('audio_transcribed_text', '') or row.get('transcribed_text', '') or ''
                    audio_filename = row.get('audio_filename', '') or ''
                    uid = _ensure_uid((row.get('uid') or '').strip(), row_count, audio_dir, audio_filename)
                    out.append(Line(
                        original_text=row.get('original_text', '') or '',
                        text=row.get('text', '') or '',
                        tts_text=row.get('tts_text', '') or '',
                        audio_duration=dur,
                        audio_filename=audio_filename,
                        audio_similarity=float(row.get('audio_similarity') or 0.0),
                        audio_format=row.get('audio_format', '') or '',
                        audio_transcribed_text=transcribed,
                        uid=uid
                    ))
            print(f"[LOAD_CSV] Wczytano {row_count} linii z CSV")
            return out
        except UnicodeDecodeError:
            print("[LOAD_CSV] UTF-8 decode failed, probuje latin-1...")
            with open(p, 'r', encoding='latin-1', newline='') as f:
                reader = csv.DictReader(f)
                row_count = 0
                for row in reader:
                    row_count += 1
                    try:
                        dur = round(float(row.get('audio_duration') or 0), 3)
                    except Exception:
                        dur = 0.0
                    transcribed = row.get('audio_transcribed_text', '') or row.get('transcribed_text', '') or ''
                    audio_filename = row.get('audio_filename', '') or ''
                    uid = _ensure_uid((row.get('uid') or '').strip(), row_count, audio_dir, audio_filename)
                    out.append(Line(
                        original_text=row.get('original_text', '') or '',
                        text=row.get('text', '') or '',
                        tts_text=row.get('tts_text', '') or '',
                        audio_duration=dur,
                        audio_filename=audio_filename,
                        audio_similarity=float(row.get('audio_similarity') or 0.0),
                        audio_format=row.get('audio_format', '') or '',
                        audio_transcribed_text=transcribed,
                        uid=uid
                    ))
            print(f"[LOAD_CSV] Wczytanych linii (latin-1): {row_count}")
            return out

    with open(p, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()

    result_lines = []
    for idx, line in enumerate(lines, start=1):
        uid = _ensure_uid('', idx, audio_dir, '')
        result_lines.append(Line(original_text=line, text=line, tts_text=line, uid=uid))

    return result_lines


def save_lines_to_file(path: str, lines: Union[List[str], List[Line]]) -> None:
    """Zapisuje linie.
    - lista Line i .csv -> zapis CSV z metadanymi
    - lista str lub .txt -> zapis jako zwykly plik tekstowy
    """
    p = Path(path)

    if (isinstance(lines, list) and lines and isinstance(lines[0], Line)) or p.suffix.lower() == '.csv':
        with open(p, 'w', encoding='utf-8', newline='') as f:
            fieldnames = [
                'original_text', 'text', 'tts_text', 'audio_duration',
                'audio_similarity', 'audio_format',
                'audio_transcribed_text', 'uid'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()

            saved_count = 0
            for item in lines:
                if isinstance(item, Line):
                    text_value, tts_value = _normalize_text_fields(item)
                    row_dict = {
                        'original_text': item.original_text,
                        'text': text_value,
                        'tts_text': tts_value,
                        'audio_duration': item.audio_duration,
                        'audio_similarity': item.audio_similarity,
                        'audio_format': item.audio_format,
                        'audio_transcribed_text': getattr(item, 'audio_transcribed_text', ''),
                        'uid': _cleanup_uid_field(getattr(item, 'uid', ''))
                    }
                    if not row_dict['uid']:
                        # Jeśli brak UID, używamy UUID jako absolutny fallback, 
                        # ale w normalnym cyklu pracy UID powinno być już nadane.
                        row_dict['uid'] = uuid.uuid4().hex[:8]
                    writer.writerow(row_dict)
                    saved_count += 1
                else:
                    writer.writerow({'original_text': item, 'text': item, 'tts_text': item})

            print(f"[SAVE_CSV] Zapisano {saved_count} linii")
    else:
        with open(p, 'w', encoding='utf-8') as f:
            if isinstance(lines, list) and lines and isinstance(lines[0], Line):
                f.write('\n'.join([l.text for l in lines]))
            else:
                f.write('\n'.join(lines))


def update_line_in_csv(csv_path: str, line_index: int, line: Line) -> None:
    """Aktualizuje pojedyncza linie w pliku CSV z danymi audio.
    Jeśli oryginalny plik to TXT, sprawdza czy już istnieje plik CSV (nie tworzy automatycznie).
    """
    p = Path(csv_path)

    # Jeśli to TXT - sprawdź czy obok nie istnieje już CSV
    if p.suffix.lower() == '.txt':
        csv_candidate = p.with_suffix('.csv')
        if csv_candidate.exists():
            csv_path = str(csv_candidate)
            p = Path(csv_path)
        else:
            # Jeśli CSV nie istnieje, nie robimy nic
            print(f"[INFO] TXT plik bez skojarzonego CSV: {csv_path}, uwaga audio metadata nie będą persystentne")
            return

    if p.suffix.lower() != '.csv':
        print(f"[WARNING] Plik nie jest CSV: {csv_path}, przerwanie zapisu audio danych")
        return

    try:
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
                    uid = _cleanup_uid_field(row.get('uid')) or uuid.uuid4().hex[:8]
                    all_lines.append(Line(
                        original_text=row.get('original_text', '') or '',
                        text=row.get('text', '') or '',
                        tts_text=row.get('tts_text', '') or '',
                        audio_duration=dur,
                        audio_filename=row.get('audio_filename', '') or '',
                        audio_similarity=(lambda v: float(v.replace(',', '.')) if isinstance(v, str) and v else float(v) if v not in (None, '') else 0.0)(row.get('audio_similarity') or row.get('similarity') or 0),
                        audio_format=row.get('audio_format', '') or row.get('ext', '') or '',
                        audio_transcribed_text=row.get('audio_transcribed_text', '') or row.get('transcribed_text', '') or '',
                        uid=uid
                    ))
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
                    uid = _cleanup_uid_field(row.get('uid')) or uuid.uuid4().hex[:8]
                    all_lines.append(Line(
                        original_text=row.get('original_text', '') or '',
                        text=row.get('text', '') or '',
                        tts_text=row.get('tts_text', '') or '',
                        audio_duration=dur,
                        audio_filename=row.get('audio_filename', '') or '',
                        audio_similarity=(lambda v: float(v.replace(',', '.')) if isinstance(v, str) and v else float(v) if v not in (None, '') else 0.0)(row.get('audio_similarity') or row.get('similarity') or 0),
                        audio_format=row.get('audio_format', '') or row.get('ext', '') or '',
                        audio_transcribed_text=row.get('audio_transcribed_text', '') or row.get('transcribed_text', '') or '',
                        uid=uid
                    ))

        if 0 <= line_index < len(all_lines):
            all_lines[line_index] = line

        with open(p, 'w', encoding='utf-8', newline='') as f:
            fieldnames = [
                'original_text', 'text', 'tts_text', 'audio_duration',
                'audio_similarity', 'audio_format',
                'audio_transcribed_text', 'uid'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for idx, item in enumerate(all_lines):
                text_value, tts_value = _normalize_text_fields(item)
                row_dict = {
                    'original_text': item.original_text,
                    'text': text_value,
                    'tts_text': tts_value,
                    'audio_duration': item.audio_duration,
                    'audio_similarity': item.audio_similarity,
                    'audio_format': item.audio_format,
                    'audio_transcribed_text': getattr(item, 'audio_transcribed_text', ''),
                    'uid': _cleanup_uid_field(getattr(item, 'uid', '')) or uuid.uuid4().hex[:8]
                }
                writer.writerow(row_dict)
    except Exception as e:
        print(f"Blad aktualizacji linii w CSV: {e}")
