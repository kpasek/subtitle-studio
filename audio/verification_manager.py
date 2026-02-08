import threading
import queue
import os
import time
import tempfile
import uuid
import json
import multiprocessing
import subprocess
import csv
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any, Tuple
from collections import Counter

from app.entity import Line
from app.io import get_audio_candidates, get_primary_audio_path

try:
    from mutagen.mp3 import MP3
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False


@dataclass
class VerificationJob:
    project_path: str
    audio_dir: str
    lines_texts: List[str]
    line_uids: List[str]
    force_refresh: bool
    ignore_short: bool
    ffprobe: Optional[str]
    workers: int
    apply_callback: Optional[Callable[[Dict[str, Any]], None]] = None


class VerificationManager:
    _instance = None
    _lock = threading.Lock()
    _whisper_model = None  # Cache dla modelu Whisper

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self.job_queue = queue.Queue()
        self.manager_thread: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()

    @classmethod
    def get_instance(cls) -> 'VerificationManager':
        return cls()

    @staticmethod
    def verify_line(
        line: Line, 
        audio_dir: str, 
        ffprobe_path: Optional[str] = None, 
        ignore_short: bool = False, 
        verify_duration: bool = True
    ) -> Dict[str, Any]:
        """
        Weryfikuje pojedynczą linię audio (istnienie pliku, czas trwania, CPS, transkrypcja).
        
        Args:
            line: Obiekt Line do weryfikacji.
            audio_dir: Ścieżka do katalogu wygenerowanego audio (root/generated).
            ffprobe_path: Opcjonalna ścieżka do ffprobe.
            ignore_short: Czy ignorować błędy CPS dla bardzo krótkich tekstów.
            verify_duration: Czy wykonywać pomiar czasu (wymaga ffprobe).
            
        Returns:
            Dict[str, Any]: Wyniki weryfikacji w formie słownika zgodnego z GUI.
        """
        audio_dir_p = Path(audio_dir) if audio_dir else Path('.')
        uid = line.uid
        text = line.get_tts_text().strip()
        
        # Inicjalizacja wyniku (id to numer porządkowy dla GUI oparty na uid lub line_id jeśli numeryczne)
        # UWAGA: GUI w subtitles.py używa int(k), gdzie k to klucz z rezultatu workera (str(i+1)).
        # Zostawiamy 'id' w słowniku, ale pobieramy go z line.uid jeśli jest numerem, lub opcjonalnie.
        # W nowym systemie UID = numer linii (1, 2, 3...) podczas importu.
        
        try:
            display_id = int(uid)
        except (ValueError, TypeError):
            display_id = 0 # fallback
            
        entry = {
            'id': display_id,
            'text': text,
            'duration': 0.0,
            'cps': 0.0,
            'raw_status': 'PENDING',
            'path': None,
            'ext': '',
            'display_status': 'PENDING'
        }
        
        if not text:
            entry.update({'raw_status': 'EMPTY', 'display_status': 'EMPTY'})
            return entry
        
        # Szukanie pliku - na podstawie UID
        audio_file, ext = VerificationManager._find_audio_for_uid(audio_dir_p, uid)
        
        if not audio_file:
            entry.update({'raw_status': 'MISSING', 'display_status': 'MISSING'})
            return entry
            
        entry.update({'path': str(audio_file), 'ext': ext})
        
        if not verify_duration:
            entry.update({'raw_status': 'OK', 'display_status': 'OK'})
            return entry
            
        # Pobieranie długości audio
        duration = VerificationManager._get_audio_duration(audio_file, ext, ffprobe_path)
        
        if duration <= 0:
            status = 'ERROR' if duration < 0 else 'EMPTY'
            entry.update({'duration': duration, 'raw_status': status, 'display_status': status})
            return entry
            
        entry['duration'] = duration
        
        # Obliczenie tempa (CPS) z uwzględnieniem pauz
        stats = Counter(text.strip('.?!'))
        pauses = (stats[','] + stats['-']) * 0.4 + (stats['.'] + stats['!'] + stats['?']) * 0.6
        time_net = duration - pauses
        
        cps = len(text) / time_net if time_net > 0 else 0.0
        entry['cps'] = cps
        entry['raw_status'] = 'OK'
        
        # Status wizualny CPS
        if ignore_short and len(text) < 5:
            entry['display_status'] = 'SHORT'
        else:
            min_cps, max_cps = 7.0, 20.0
            if cps < min_cps:
                entry['display_status'] = f"ZA WOLNO (<{min_cps:.1f})"
            elif cps > max_cps:
                entry['display_status'] = f"ZA SZYBKO (>{max_cps:.1f})"
            else:
                entry['display_status'] = 'OK'
        
        # Weryfikacja similarity i transkrypcji via Whisper
        entry['similarity'] = 0.0
        entry['transcribed_text'] = ''
        
        try:
            sim_result = VerificationManager.verify_similarity(line, audio_file)
            if sim_result.get('success'):
                entry['similarity'] = sim_result.get('similarity', 0.0)
                entry['transcribed_text'] = sim_result.get('transcribed_text', '')
        except Exception:
            pass
        
        return entry

    @staticmethod
    def _find_audio_for_uid(audio_dir: Path, uid: str) -> Tuple[Optional[Path], str]:
        """Pomocnicza metoda do znajdowania pliku audio po UID."""
        candidates = get_audio_candidates(uid)
        if candidates:
            path, is_ready = candidates[0]
            ext = path.suffix.lower().lstrip('.')
            return path, ext
        return None, ''


    @staticmethod
    def _get_audio_duration(file_path: Path, ext: str, ffprobe_path: Optional[str] = None) -> float:
        """
        Pobiera długość pliku audio.
        
        Returns:
            float: Długość w sekundach, -1.0 jeśli błąd, 0.0 jeśli plik pusty
        """
        file_path = str(file_path)
        
        # Próba z mutagen dla MP3
        if ext == 'mp3' and MUTAGEN_AVAILABLE:
            try:
                duration = MP3(file_path).info.length
                return duration
            except Exception:
                pass
        
        # Próba z ffprobe
        if ffprobe_path and os.path.exists(ffprobe_path):
            try:
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                cmd = [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                       "-of", "default=noprint_wrappers=1:nokey=1", file_path]
                
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    startupinfo=startupinfo, timeout=10)
                
                if res.returncode == 0 and res.stdout.strip():
                    duration = float(res.stdout.strip())
                    return duration
                else:
                    return -1.0
            except Exception:
                return -1.0
        
        return -1.0

    @staticmethod
    def _get_whisper_model():
        """Załaduj model Whisper z cache'iem - aby nie ładować za każdym razem."""
        if VerificationManager._whisper_model is None:
            print(f"[INFO] Ładuję model Whisper (po raz pierwszy)...")
            try:
                # Sprawdź czy CUDA jest dostępne
                import torch
                if torch.cuda.is_available():
                    print(f"[INFO] CUDA dostępne, próbuję załadować na GPU...")
                    try:
                        VerificationManager._whisper_model = whisper.load_model("base", device="cuda")
                        print(f"[INFO] Model załadowany na GPU (CUDA)")
                    except Exception as cuda_err:
                        print(f"[WARNING] Błąd ładowania na CUDA: {cuda_err}")
                        print(f"[INFO] Załaduję na CPU zamiast...")
                        VerificationManager._whisper_model = whisper.load_model("base", device="cpu")
                        print(f"[INFO] Model załadowany na CPU")
                else:
                    print(f"[INFO] CUDA niedostępne, załaduję na CPU...")
                    VerificationManager._whisper_model = whisper.load_model("base", device="cpu")
                    print(f"[INFO] Model załadowany na CPU")
            except Exception as e:
                print(f"[ERROR] Nie mogę załadować modelu Whisper: {e}")
                import traceback
                traceback.print_exc()
                raise
        return VerificationManager._whisper_model

    @staticmethod
    def _clean_non_latin_chars(text: str) -> str:
        """
        Usuwa znaki spoza alfabetu łacińskiego i polskiego.
        Zachowuje: litery (A-Z, a-z), znaki polskie (ąćęłńóśźż), spacje i znaki interpunkcyjne.
        Usuwa: znaki chińskie, cyrylice, hieroglify, itp.
        """
        import re
        # Zachowaj tylko znaki łacińskie (ASCII), polskie i spacje
        # \w w unicode daje literki ale też cyfry i _
        # Będziemy bardziej selektywni: ASCII (a-z, A-Z, 0-9) + znaki polskie + spacje + znaki interpunkcyjne
        
        # Znaki polskie: ąćęłńóśźż (małe) i ĄĆĘŁŃÓŚŹŻ (duże)
        allowed_pattern = r"[a-zA-Z0-9ąćęłńóśźżĄĆĘŁŃÓŚŹŻ\s.,!?\-;:\'\"]"
        
        # Zachowaj tylko znaki z allowed_pattern
        cleaned = ''.join(char for char in text if re.match(allowed_pattern, char, re.UNICODE))
        
        # Usuń wielokrotne spacje
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        if cleaned != text:
            print(f"[INFO] Oczyszczenie tekstu z obcych znaków:")
            print(f"  Przed: {repr(text)}")
            print(f"  Po:    {repr(cleaned)}")
        
        return cleaned

    @staticmethod
    def verify_similarity(line, audio_path: str) -> dict:
        """
        Weryfikuje similarity poprzez speech-to-text.
        Konwertuje audio do tekstu za pomocą Whisper i porównuje z oryginalnym tekstem.
        
        Args:
            line: Obiekt Line do weryfikacji
            audio_path: Ścieżka do pliku audio
            
        Returns:
            dict: Słownik z wynikami {'similarity': float, 'transcribed_text': str, 'success': bool}
        """
        result = {
            'similarity': 0.0,
            'transcribed_text': '',
            'success': False,
            'error': None
        }

        if not RAPIDFUZZ_AVAILABLE:
            result['error'] = 'rapidfuzz library not available'
            return result
        
        # Jeśli brak bibliotek
        if not WHISPER_AVAILABLE or not RAPIDFUZZ_AVAILABLE:
            error_msg = 'Brak bibliotek (Whisper lub RapidFuzz)'
            result['error'] = error_msg
            return result
        
        audio_path = str(audio_path)
        if not os.path.exists(audio_path):
            result['error'] = f'Plik audio nie istnieje'
            return result
        
        # Sprawdzenie rozmiaru pliku
        file_size = os.path.getsize(audio_path)
        if file_size < 1000:
            result['error'] = f'Plik audio zbyt mały'
            return result
        
        # Konwersja audio do tekstu
        try:
            model = VerificationManager._get_whisper_model()
            
            # Sprawdzenie czy model jest na CPU, jeśli tak wyłącz FP16
            import torch
            fp16 = True
            try:
                if next(model.parameters()).device.type == 'cpu':
                    fp16 = False
            except:
                pass
            
            # Wyłącz warningi z Whisper'a dla CPU
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*Performing inference on CPU.*")
                warnings.filterwarnings("ignore", message=".*FP16 is not supported on CPU.*")
                
                transcription_result = model.transcribe(audio_path, language="pl", fp16=fp16)
                transcribed_text = transcription_result.get("text", "").strip()
            
            # Usuń znaki spoza alfabetu łacińskiego i polskiego
            transcribed_text = VerificationManager._clean_non_latin_chars(transcribed_text)
            
            # Fallback jeśli brak tekstu z language="pl"
            if not transcribed_text:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message=".*Performing inference on CPU.*")
                    warnings.filterwarnings("ignore", message=".*FP16 is not supported on CPU.*")
                    
                    transcription_result = model.transcribe(audio_path, fp16=fp16)
                    transcribed_text = transcription_result.get("text", "").strip()
                    transcribed_text = VerificationManager._clean_non_latin_chars(transcribed_text)
        except Exception as e:
            result['error'] = f'Błąd transkrypcji: {str(e)}'
            return result
        
        # Porównanie z oryginalnym tekstem
        try:
            original_text = line.get_text().strip()
            tts_text = line.get_tts_text().strip()
            
            # Oczyszczenie tekstów - usunięcie znaków specjalnych, średniki, etc.
            import re
            def clean_text(text):
                # Usunięcie znaków specjalnych oprócz spacji, zachowanie tylko liter, cyfr i spacji
                text = re.sub(r'[^\w\s]', ' ', text, flags=re.UNICODE)
                # Zamiana wielkich spacji na pojedynczą
                text = re.sub(r'\s+', ' ', text)
                return text.strip()
            
            cleaned_transcribed = clean_text(transcribed_text)
            cleaned_tts = clean_text(tts_text)
            
            # Porównanie z tekstem do TTS - token sort ratio jest bardziej tolerancyjny
            # Porównujemy oczyszczone teksty (tylko słowa, bez znaków specjalnych)
            similarity = fuzz.token_sort_ratio(cleaned_transcribed, cleaned_tts) / 100.0
            
            result['similarity'] = similarity
            result['transcribed_text'] = transcribed_text
            result['success'] = True
            
        except Exception as e:
            result['error'] = f'Błąd porównania: {str(e)}'
            return result
        
        return result

    @staticmethod
    def apply_similarity_to_line(line: Line, audio_path: str) -> Line:
        """
        Weryfikuje similarity i aktualizuje obiekt Line.
        
        Args:
            line: Obiekt Line do aktualizacji
            audio_path: Ścieżka do pliku audio
            
        Returns:
            Line: Zmodyfikowany obiekt Line
        """
        try:
            result = VerificationManager.verify_similarity(line, audio_path)
            
            if result.get('success'):
                line.audio_similarity = result.get('similarity', 0.0)
                line.audio_transcribed_text = result.get('transcribed_text', '')
                print(f"[DEBUG] apply_similarity_to_line: set audio_transcribed_text = {repr(line.audio_transcribed_text)}")
            else:
                line.audio_similarity = 0.0
                line.audio_transcribed_text = ''
            
            return line
        except Exception as e:
            print(f"[ERROR] apply_similarity_to_line exception: {e}")
            return line

    def add_job(self, job: VerificationJob):
        self.job_queue.put(job)
        self._start_thread_if_needed()

    def _start_thread_if_needed(self):
        if self.manager_thread is None or not self.manager_thread.is_alive():
            self.manager_thread = threading.Thread(target=self._process_queue, daemon=True)
            self.manager_thread.start()

    def cancel_current(self):
        self.cancel_event.set()

    def _process_queue(self):
        while not self.job_queue.empty():
            job: VerificationJob = self.job_queue.get()
            self.cancel_event.clear()
            try:
                self._run_verification_job(job)
            except Exception:
                pass
        self.manager_thread = None

    def _run_verification_job(self, job: VerificationJob):
        # spawn worker processes that write per-worker JSON files
        tmpdir = tempfile.gettempdir()
        uid = uuid.uuid4().hex
        workers = max(1, job.workers)
        out_files = []
        procs = []
        for wi in range(workers):
            out_path = str(Path(tmpdir) / f"cps_worker_{uid}.{wi}.json")
            p = multiprocessing.Process(
                target=_verification_process_entry,
                args=(job.audio_dir, job.lines_texts, job.line_uids, out_path, job.ffprobe or '', job.force_refresh, job.ignore_short, wi, workers)
            )
            p.start()
            procs.append(p)
            out_files.append(out_path)

        last_mtimes = {str(p): 0 for p in out_files}

        # monitor outputs and call apply_callback with merged results
        aggregated: Dict[str, Any] = {}
        while not self.cancel_event.is_set():
            any_alive = any(p.is_alive() for p in procs)
            changed = False
            for outp in list(out_files):
                pth = Path(outp)
                if not pth.exists():
                    continue
                try:
                    m = pth.stat().st_mtime
                except Exception:
                    continue
                if m == last_mtimes.get(outp):
                    continue
                last_mtimes[outp] = m
                try:
                    with open(pth, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    continue
                # merge
                for k, v in data.items():
                    aggregated[k] = v
                    changed = True

            if changed and job.apply_callback:
                try:
                    job.apply_callback(aggregated.copy())
                except Exception:
                    pass

            if not any_alive:
                break

            time.sleep(0.5)

        # final callback with aggregated results
        if job.apply_callback:
            try:
                job.apply_callback(aggregated.copy())
            except Exception:
                pass
            # notify finished
            try:
                job.apply_callback({'__done': True})
            except Exception:
                pass

        # cleanup
        for outp in out_files:
            try:
                p = Path(outp)
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    @staticmethod
    def save_verification_results_to_csv(results: List[dict], csv_path: str) -> bool:
        """
        Zapisuje wyniki weryfikacji do pliku CSV.
        
        Args:
            results: Lista słowników z wynikami
            csv_path: Ścieżka do pliku CSV
            
        Returns:
            bool: True jeśli sukces
        """
        try:
            csv_path = Path(csv_path)
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            
            if not results:
                return False
            
            fieldnames = ['id', 'text', 'duration', 'cps', 'raw_status', 'path', 'ext', 'display_status', 'similarity']
            
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for result in results:
                    row = {field: result.get(field, '') for field in fieldnames}
                    writer.writerow(row)
            
            return True
        except Exception:
            return False


# --- worker entry (updated to use verify_line static method) ---
def _verification_process_entry(audio_dir: str, lines_texts: list, line_uids: list, out_file: str, ffprobe_path: str, force_refresh: bool, ignore_short: bool, worker_idx: int = 0, total_workers: int = 1):
    """
    Pracownik procesu do weryfikacji audio.
    Zapisuje wyniki do JSON.
    """
    import json
    from pathlib import Path
    from app.entity import Line
    
    results = {}
    
    def write_atomic(dct):
        tmp = Path(out_file + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as tf:
            json.dump(dct, tf, ensure_ascii=False)
        tmp.replace(out_file)
    
    def _normalize_uid(uid: str) -> str:
        """Konwertuje sam UUID na pełną nazwę pliku output1 (uid)"""
        return f"output1 ({uid})"

    for i, text in enumerate(lines_texts):
        if total_workers and (i % total_workers) != worker_idx:
            continue
        
        ident = str(i + 1)
        uid = line_uids[i] if line_uids and i < len(line_uids) else ''
        
        # Tworzenie obiektu Line z poprawnym UID
        line = Line(original_text=text, text=text, tts_text=text.strip(), uid=uid)
        
        # Weryfikacja linii (teraz z obiektem Line jako głównym źródłem danych)
        result = VerificationManager.verify_line(
            line=line,
            audio_dir=audio_dir,
            ffprobe_path=ffprobe_path if ffprobe_path else None,
            ignore_short=ignore_short
        )
        
        # Nadpisujemy 'id' wynikiem 'i + 1', bo worker używa indeksu pętli 
        # do komunikacji z GUI (które mapuje k-1 -> index)
        result['id'] = i + 1
        
        results[ident] = result
        write_atomic(results)
    
    write_atomic(results)
