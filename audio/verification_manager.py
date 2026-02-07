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
from typing import Callable, Optional, List, Dict, Any
from collections import Counter

from app.entity import Line

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
    def verify_line(line, audio_dir: str, line_id: int, ffprobe_path: Optional[str] = None, ignore_short: bool = False, verify_duration: bool = True) -> 'dict':
        """
        Weryfikuje pojedynczą linię audio.
        
        Args:
            line: Obiekt Line do weryfikacji
            audio_dir: Ścieżka do katalogu audio
            line_id: ID linii (numer)
            ffprobe_path: Ścieżka do ffprobe
            ignore_short: Czy ignorować krótkie napisy
            
        Returns:
            dict: Słownik z wynikami weryfikacji
        """
        from app.entity import Line
        
        audio_dir_p = Path(audio_dir) if audio_dir else Path('.')
        ident_str = str(line_id)
        
        # Inicjalizacja wyniku
        entry = {
            'id': line_id,
            'text': line.tts_text.strip() if line.tts_text else '',
            'duration': 0.0,
            'cps': 0.0,
            'raw_status': 'PENDING',
            'path': None,
            'ext': '',
            'display_status': 'PENDING'
        }
        
        text_clean = line.tts_text.strip() if line.tts_text else ''
        
        # Jeśli brak tekstu, zwróć pusty wynik
        if not text_clean:
            entry['raw_status'] = 'EMPTY'
            entry['display_status'] = 'EMPTY'
            return entry
        
        # Szukanie pliku audio
        audio_file = None
        found_ext = ''
        candidates = [
            (audio_dir_p / f"output1 ({ident_str}).wav", 'wav'),
            (audio_dir_p / f"output1 ({ident_str}).mp3", 'mp3'),
            (audio_dir_p / 'ready' / f"output1 ({ident_str}).ogg", 'ogg'),
            (audio_dir_p / 'ready' / f"output1 ({ident_str}).mp3", 'mp3')
        ]
        
        for p, ext in candidates:
            if p.exists():
                audio_file = p
                found_ext = ext
                break
        
        # Jeśli plik nie istnieje
        if not audio_file:
            entry['raw_status'] = 'MISSING'
            entry['display_status'] = 'MISSING'
            return entry
        
        entry['path'] = str(audio_file)
        entry['ext'] = found_ext

        # If duration verification is disabled, skip computing duration/CPS
        if not verify_duration:
            entry['duration'] = 0.0
            entry['cps'] = 0.0
            entry['raw_status'] = 'OK'
            entry['display_status'] = 'OK'
            return entry
        
        # Pobieranie długości audio
        duration = VerificationManager._get_audio_duration(audio_file, found_ext, ffprobe_path)
        
        if duration < 0:
            entry['duration'] = duration
            entry['raw_status'] = 'ERROR'
            entry['display_status'] = 'ERROR'
            return entry
        
        if duration == 0:
            entry['duration'] = 0.0
            entry['raw_status'] = 'EMPTY'
            entry['display_status'] = 'EMPTY'
            return entry
        
        entry['duration'] = duration
        
        # Obliczenie CPS
        stats = Counter(text_clean.strip('.?!'))
        short = stats[','] + stats['-']
        long = stats['.'] + stats['!'] + stats['?']
        pauses = (short * 0.4) + (long * 0.6)
        
        try:
            cps = len(text_clean) / (duration - pauses) if (duration - pauses) > 0 else 0.0
        except:
            cps = 0.0
        
        entry['cps'] = cps
        entry['raw_status'] = 'OK'
        
        # Określenie status wyświetlania
        if ignore_short and len(text_clean) < 5:
            entry['display_status'] = 'SHORT'
        else:
            min_cps = 7.0
            max_cps = 20.0
            if cps < min_cps:
                entry['display_status'] = f"ZA WOLNO (<{min_cps:.1f})"
            elif cps > max_cps:
                entry['display_status'] = f"ZA SZYBKO (>{max_cps:.1f})"
            else:
                entry['display_status'] = 'OK'
        
        return entry

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
        
        # Jeśli brak bibliotek
        if not WHISPER_AVAILABLE or not RAPIDFUZZ_AVAILABLE:
            error_msg = 'Brak bibliotek do weryfikacji similarity'
            result['error'] = error_msg
            return result
        
        audio_path = str(audio_path)
        if not os.path.exists(audio_path):
            error_msg = f'Plik audio nie istnieje: {audio_path}'
            result['error'] = error_msg
            print(f"[ERROR] {error_msg}")
            return result
        
        # Sprawdzenie rozmiaru pliku
        file_size = os.path.getsize(audio_path)
        print(f"[DEBUG] Plik audio: {audio_path}, rozmiar={file_size} bajtów")
        
        if file_size < 1000:
            error_msg = f'Plik audio zbyt mały: {file_size} bajtów'
            result['error'] = error_msg
            print(f"[WARNING] {error_msg}")
            return result
        
        # Konwersja audio do tekstu
        try:
            model = VerificationManager._get_whisper_model()
            
            print(f"[INFO] Transkrybuję: {audio_path}")
            
            # Sprawdzenie czy model jest na CPU, jeśli tak wyłącz FP16
            import torch
            fp16 = True
            try:
                if next(model.parameters()).device.type == 'cpu':
                    fp16 = False
                    print(f"[INFO] Model na CPU - wyłączam FP16")
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
            print(f"[DEBUG] Pełny wynik Whisper: {transcription_result}")
            print(f"[DEBUG] Transkrybowany tekst (PL): {repr(transcribed_text)}")
            
            # Fallback jeśli brak tekstu z language="pl"
            if not transcribed_text:
                print(f"[WARNING] Transkrypcja z language='pl' zwróciła pusty tekst, próbuję bez language...")
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message=".*Performing inference on CPU.*")
                    warnings.filterwarnings("ignore", message=".*FP16 is not supported on CPU.*")
                    
                    transcription_result = model.transcribe(audio_path, fp16=fp16)
                    transcribed_text = transcription_result.get("text", "").strip()
                    transcribed_text = VerificationManager._clean_non_latin_chars(transcribed_text)
                
                print(f"[DEBUG] Transkrybowany tekst (AUTO): {repr(transcribed_text)}")
        except Exception as e:
            error_msg = f'Błąd transcripcji: {str(e)}'
            result['error'] = error_msg
            print(f"[ERROR] {error_msg}")
            import traceback
            traceback.print_exc()
            return result
        
        # Porównanie z oryginalnym tekstem
        try:
            original_text = line.original_text.strip()
            tts_text = line.tts_text.strip()
            
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
            print(f"[DEBUG] verify_similarity:")
            print(f"  Oryginalny transkrybowany: {repr(transcribed_text)}")
            print(f"  Oczyszczony transkrybowany: {repr(cleaned_transcribed)}")
            print(f"  Oczyszczony TTS: {repr(cleaned_tts)}")
            print(f"  Similarity: {similarity:.2%}")
            
        except Exception as e:
            error_msg = f'Błąd porównania: {str(e)}'
            result['error'] = error_msg
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
                args=(job.audio_dir, job.lines_texts, out_path, job.ffprobe or '', job.force_refresh, job.ignore_short, wi, workers)
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
def _verification_process_entry(audio_dir: str, lines_texts: list, out_file: str, ffprobe_path: str, force_refresh: bool, ignore_short: bool, worker_idx: int = 0, total_workers: int = 1):
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
    
    for i, text in enumerate(lines_texts):
        if total_workers and (i % total_workers) != worker_idx:
            continue
        
        ident = str(i + 1)
        
        # Tworzenie obiektu Line
        line = Line(original_text=text, text=text, tts_text=text.strip())
        
        # Weryfikacja linii
        result = VerificationManager.verify_line(
            line=line,
            audio_dir=audio_dir,
            line_id=i + 1,
            ffprobe_path=ffprobe_path if ffprobe_path else None,
            ignore_short=ignore_short
        )
        
        results[ident] = result
        write_atomic(results)
    
    write_atomic(results)
