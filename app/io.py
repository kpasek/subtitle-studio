import os
from pathlib import Path
import json
import sys
from typing import Callable, Optional, Dict, List, Union, Tuple
import csv
import uuid

from app.entity import Line


if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    home = Path.home()
    application_path = home / '.config'

APP_CONFIG = os.path.join(application_path, "subtitle-studio.json")

_csv_cache_data: List[Dict] = []
_csv_cache_path: Optional[str] = None
_csv_cache_mtime: float = 0
_project_path_provider: Optional[Callable[[], Optional[str]]] = None

def set_project_path_provider(provider: Callable[[], Optional[str]]):
    """Ustawia funkcję zwracającą aktualną ścieżkę do pliku projektu."""
    global _project_path_provider
    _project_path_provider = provider

def _get_effective_csv_path(passed_path: Optional[str]) -> Optional[str]:
    if passed_path:
        return passed_path
    if _project_path_provider:
        return _project_path_provider()
    return None

def _ensure_csv_cache(path: str) -> bool:
    """Wczytuje CSV do pamięci, jeśli jeszcze go nie ma lub plik się zmienił."""
    global _csv_cache_data, _csv_cache_path, _csv_cache_mtime
    p = Path(path)
    if not p.exists():
        return False
        
    try:
        current_mtime = p.stat().st_mtime
        if _csv_cache_path == path and _csv_cache_mtime == current_mtime:
            return True
            
        with open(p, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            _csv_cache_data = list(reader)
            
        _csv_cache_path = path
        _csv_cache_mtime = current_mtime
        return True
    except Exception as e:
        print(f"[CSV_CACHE_ERR] {e}")
        return False

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


_current_audio_dir: Optional[Path] = None

def set_audio_dir(path: Optional[Union[str, Path]]):
    """Ustawia globalną ścieżkę do katalogu generated audio."""
    global _current_audio_dir
    if path:
        _current_audio_dir = Path(path)
    else:
        _current_audio_dir = None

def get_audio_dir() -> Optional[Path]:
    """Pobiera obecny katalog generated audio."""
    return _current_audio_dir

def get_primary_audio_path(uid: str) -> Optional[Path]:
    """Zwraca ścieżkę do podstawowego pliku audio."""
    if not uid or not _current_audio_dir:
        return None
    
    p_wav = _current_audio_dir / f"output1 ({uid}).wav"
    if p_wav.exists():
        return p_wav
        
    p_mp3 = _current_audio_dir / f"output1 ({uid}).mp3"
    if p_mp3.exists():
        return p_mp3
        
    return p_wav

def get_audio_candidates(uid: str) -> List[Tuple[Path, bool]]:
    """Zwraca wszystkie możliwe pliki audio dla danego UID."""
    if not uid or not _current_audio_dir:
        return []
        
    uid_str = str(uid).strip()
    bases = [f"output1 ({uid_str})", f"output1({uid_str})", uid_str]
    
    gen_dir = _current_audio_dir
    ready_dir = gen_dir.parent / "ready"
    
    found = []
    extensions = ['wav', 'mp3', 'ogg', 'WAV', 'MP3', 'OGG']
    
    for base in bases:
        for ext in extensions:
            p = gen_dir / f"{base}.{ext}"
            if p.exists():
                if not any(f[0].resolve() == p.resolve() for f in found):
                    found.append((p, False))
        
        for ext in extensions:
            p = ready_dir / f"{base}.{ext}"
            if p.exists():
                if not any(f[0].resolve() == p.resolve() for f in found):
                    found.append((p, True))
                    
    return found


def _normalize_text_fields(line: Line) -> Tuple[str, str]:
    """Zwraca wartości `text` i `tts_text`, pomijając duplikaty względem oryginału."""
    original = line.original_text or ''
    text_value = line.text or ''
    text_for_csv = text_value if text_value and text_value != original else ''
    base_text = text_for_csv or original
    
    # Obsługa pustego tts_text
    if line.tts_text == "":
         tts_for_csv = "<SILENCE>" if base_text != "" else "" 
    else:
        tts_value = line.tts_text or ''
        tts_for_csv = tts_value if tts_value and tts_value != base_text else ''
        
    return text_for_csv, tts_for_csv


def load_subtitle_file(path: str, audio_dir: Optional[Path] = None) -> List[Line]:
    """Wczytuje plik napisów (CSV lub TXT)."""
    p = Path(path)

    def _ensure_uid(value: str, idx: int, audio_dir_path: Optional[Path], audio_filename: str) -> str:
        normalized_value = _cleanup_uid_field(value)
        if normalized_value:
            return normalized_value

        inferred = _extract_uid_component(audio_filename)
        if inferred:
            return inferred

        if audio_dir_path and audio_dir_path.is_dir():
            pattern_candidates = [f"output1 ({idx})", str(idx)]
            for pattern in pattern_candidates:
                for ext in ['.wav', '.mp3']:
                    candidate = audio_dir_path / f"{pattern}{ext}"
                    if candidate.exists():
                        return str(idx)

        return uuid.uuid4().hex[:8]

    
    def _load_csv_file(f) -> List[Line]:
        reader = csv.DictReader(f)
        row_count = 0
        for row in reader:
            row_count += 1
            try:
                dur = round(float(row.get('audio_duration') or 0), 3)
            except Exception:
                dur = 0.0
            
            # Load TTS Text handling Silence
            tts_raw = row.get('tts_text', '') or ''
            if tts_raw == '<SILENCE>':
                tts_final = ""
            elif tts_raw == '':
                tts_final = None
            else:
                tts_final = tts_raw

            transcribed = row.get('audio_transcribed_text', '') or ''
            audio_filename = row.get('audio_filename', '') or ''
            uid = _ensure_uid((row.get('uid') or '').strip(), row_count, audio_dir, audio_filename)
            out.append(Line(
                original_text=row.get('original_text', '') or '',
                text=row.get('text', '') or None,
                tts_text=tts_final,
                audio_duration=dur,
                audio_filename=audio_filename,
                audio_similarity=float(row.get('audio_similarity') or 0.0),
                audio_format=row.get('audio_format', '') or '',
                audio_transcribed_text=transcribed,
                audio_hallucination=row.get('audio_hallucination', 'PENDING'),
                status_flag=row.get('status_flag', None),
                ai_processed=str(row.get('ai_processed', 'False')).lower() == 'true',
                uid=uid
            ))

        return out
    
    if p.suffix.lower() == '.csv':
        out: List[Line] = []
        try:
            with open(p, 'r', encoding='utf-8', newline='') as f:
                return _load_csv_file(f)
        except UnicodeDecodeError:
            print("[LOAD_CSV] UTF-8 decode failed, probuje latin-1...")
            with open(p, 'r', encoding='latin-1', newline='') as f:
                return _load_csv_file(f)        

    with open(p, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()

    result_lines = []
    for idx, line in enumerate(lines, start=1):
        uid = _ensure_uid('', idx, audio_dir, '')
        result_lines.append(Line(original_text=line, text=line, tts_text=line, uid=uid))

    return result_lines


def save_lines_to_file(path: str, lines: Union[List[str], List[Line]]) -> None:
    """Zapisuje linie.
    - lista Line i .csv -> zapis CSV z metadanymi (sortowane po UID)
    - lista str lub .txt -> zapis jako zwykly plik tekstowy
    """
    global _csv_cache_data, _csv_cache_path, _csv_cache_mtime
    p = Path(path)

    if (isinstance(lines, list) and lines and isinstance(lines[0], Line)) or p.suffix.lower() == '.csv':
        # Sortowanie po UID dla zachowania spójności pliku
        if isinstance(lines, list) and lines and isinstance(lines[0], Line):
            lines = sorted(lines, key=lambda l: str(l.uid))

        temp_path = p.with_suffix(p.suffix + ".tmp")
        try:
            with open(temp_path, 'w', encoding='utf-8', newline='') as f:
                fieldnames = [
                    'original_text', 'text', 'tts_text', 'audio_duration',
                    'audio_similarity', 'audio_format', 'audio_filename',
                    'audio_transcribed_text', 'audio_hallucination', 'status_flag', 'ai_processed', 'uid'
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
                writer.writeheader()

                saved_count = 0
                rows_for_cache = []
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
                            'audio_filename': item.audio_filename, 
                            'audio_transcribed_text': item.audio_transcribed_text,
                            'audio_hallucination': item.audio_hallucination,
                            'status_flag': item.status_flag,
                            'ai_processed': str(item.ai_processed),
                            'uid': _cleanup_uid_field(item.uid)  
                        }
                        if not row_dict['uid']:
                            row_dict['uid'] = uuid.uuid4().hex[:8]
                        writer.writerow(row_dict)
                        rows_for_cache.append(row_dict)
                        saved_count += 1
                    else:
                        writer.writerow({'original_text': item, 'text': item, 'tts_text': item})

            # Atomowa zamiana plików
            temp_path.replace(p)
            
            # Aktualizacja cache
            _csv_cache_data = rows_for_cache
            _csv_cache_path = str(p)
            _csv_cache_mtime = p.stat().st_mtime
            
            print(f"[SAVE_CSV] Zapisano {saved_count} linii (posortowano po UID)")
        finally:
            if temp_path.exists():
                try: temp_path.unlink()
                except: pass
    else:
        temp_path = p.with_suffix(p.suffix + ".txt.tmp")
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                if isinstance(lines, list) and lines and isinstance(lines[0], Line):
                    f.write('\n'.join([l.text for l in lines]))
                else:
                    f.write('\n'.join(lines))
            temp_path.replace(p)
        finally:
            if temp_path.exists():
                try: temp_path.unlink()
                except: pass



def update_lines_in_csv(lines_to_update: List[Line], csv_path: Optional[str] = None) -> int:
    """
    Aktualizuje wiersze w pliku CSV na podstawie UID (używa cache).
    Jeśli UID istnieje - nadpisuje, jeśli nie - dodaje. Wynik jest sortowany po UID.
    """
    global _csv_cache_data, _csv_cache_mtime
    path = _get_effective_csv_path(csv_path)
    if not path:
        return 0
        
    p = Path(path)
    if not p.exists():
        save_lines_to_file(str(p), lines_to_update)
        return len(lines_to_update)

    _ensure_csv_cache(str(p))
    
    updates_dict = {str(l.uid): l for l in lines_to_update}
    updated_count = 0
    new_cache = []
    seen_uids = set()
    
    # 1. Aktualizacja istniejących w cache
    for row in _csv_cache_data:
        uid = row.get('uid', '')
        if uid in updates_dict:
            line = updates_dict[uid]
            text_value, tts_value = _normalize_text_fields(line)
            new_row = {
                'original_text': line.original_text,
                'text': text_value,
                'tts_text': tts_value,
                'audio_duration': line.audio_duration,
                'audio_similarity': line.audio_similarity,
                'audio_format': line.audio_format,
                'audio_filename': line.audio_filename,
                'audio_transcribed_text': line.audio_transcribed_text,
                'audio_hallucination': line.audio_hallucination,
                'status_flag': (getattr(line, 'status_flag', None) or ''),
                'ai_processed': str(getattr(line, 'ai_processed', False)),
                'uid': uid
            }
            new_cache.append(new_row)
            seen_uids.add(uid)
            updated_count += 1
        else:
            new_cache.append(row)
            seen_uids.add(uid)

    # 2. Dodanie nowych
    for uid, line in updates_dict.items():
        if uid not in seen_uids:
            text_value, tts_value = _normalize_text_fields(line)
            new_row = {
                'original_text': line.original_text,
                'text': text_value,
                'tts_text': tts_value,
                'audio_duration': line.audio_duration,
                'audio_similarity': line.audio_similarity,
                'audio_format': line.audio_format,
                'audio_filename': line.audio_filename,
                'audio_transcribed_text': line.audio_transcribed_text,
                'audio_hallucination': line.audio_hallucination,
                'status_flag': (getattr(line, 'status_flag', None) or ''),
                'ai_processed': str(getattr(line, 'ai_processed', False)),
                'uid': uid
            }
            new_cache.append(new_row)
            updated_count += 1

    # Sortowanie po UID dla zachowania spójności
    new_cache.sort(key=lambda x: str(x.get('uid', '')))
    
    fieldnames = [
        'original_text', 'text', 'tts_text', 'audio_duration',
        'audio_similarity', 'audio_format', 'audio_filename',
        'audio_transcribed_text', 'audio_hallucination', 'status_flag', 'ai_processed',
        'uid'
    ]
    
    try:

        temp_path = p.with_suffix(p.suffix + ".upd.tmp")
        try:
            with open(temp_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                writer.writerows(new_cache)
            temp_path.replace(p)
            
            _csv_cache_data = new_cache
            _csv_cache_mtime = p.stat().st_mtime
        finally:
            if temp_path.exists():
                try: temp_path.unlink()
                except: pass
                
        return updated_count
    except Exception as e:
        print(f"[UPDATE_CSV_ERR] {e}")
        return 0


def update_line_in_csv(line: Line, csv_path: Optional[str] = None) -> bool:
    """Aktualizuje pojedynczą linię w pliku CSV (alias dla update_lines_in_csv)."""
    return update_lines_in_csv([line], csv_path) > 0


def delete_lines_from_csv(uids_to_delete: List[str], csv_path: Optional[str] = None) -> int:
    """
    Usuwa wiersze z pliku CSV na podstawie listy UID.
    """
    global _csv_cache_data, _csv_cache_mtime
    path = _get_effective_csv_path(csv_path)
    if not path:
        return 0
        
    p = Path(path)
    if not p.exists():
        return 0

    _ensure_csv_cache(str(p))
    
    uid_set = set(str(uid) for uid in uids_to_delete)
    
    initial_count = len(_csv_cache_data)
    new_cache = [row for row in _csv_cache_data if row.get('uid', '') not in uid_set]
    
    deleted_count = initial_count - len(new_cache)
    if deleted_count == 0:
        return 0

    # Ensure all fields are valid for CSV (no None values for status_flag, etc.)
    processed_cache = []
    for row in new_cache:
        row = dict(row)  # copy
        # Normalize status_flag and ai_processed
        row['status_flag'] = row.get('status_flag') or ''
        row['ai_processed'] = str(row.get('ai_processed', False))
        processed_cache.append(row)

    _csv_cache_data = processed_cache

    fieldnames = [
        'original_text', 'text', 'tts_text', 'audio_duration',
        'audio_similarity', 'audio_format', 'audio_filename',
        'audio_transcribed_text', 'audio_hallucination', 'status_flag', 'ai_processed',
        'uid'
    ]

    try:
        temp_path = p.with_suffix(p.suffix + ".del.tmp")
        try:
            with open(temp_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                writer.writerows(processed_cache)
            temp_path.replace(p)

            _csv_cache_mtime = p.stat().st_mtime
        finally:
            if temp_path.exists():
                try: temp_path.unlink()
                except: pass

        return deleted_count
    except Exception as e:
        print(f"[DELETE_CSV_ERR] {e}")
        return 0