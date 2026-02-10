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
import shutil
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any, Tuple
from collections import Counter

from app.entity import Line
from app.io import get_audio_candidates, get_primary_audio_path, set_audio_dir, get_audio_dir
from app.worker import Worker, BatchResultTracker
from dataclasses import asdict

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
    lines: List[Line]
    line_uids: List[str]
    force_refresh: bool
    ignore_short: bool
    ffprobe: Optional[str]
    workers: int
    verify_hallucination: bool = False
    verify_similarity: bool = False
    apply_callback: Optional[Callable[[Dict[str, Any]], None]] = None


class VerificationManager:
    _instance = None
    _lock = threading.Lock()
    _whisper_model = None  # Cache dla modelu Whisper
    _model_lock = threading.Lock()

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
        self.worker: Optional[Worker] = None

    @classmethod
    def get_instance(cls) -> 'VerificationManager':
        return cls()

    @staticmethod
    def verify_line(
        line: Line, 
        ffprobe_path: Optional[str] = None, 
        verify_duration: bool = True,
        verify_hallucination: bool = True,
        verify_similarity: bool = False,
        force_refresh: bool = False
    ) -> Tuple[Line, bool]:
        """
        Weryfikuje pojedynczą linię audio i aktualizuje obiekt Line.
        Zwraca (Line, czy_zmodyfikowano).
        """
        # Zapamiętujemy stan przed (uproszczony snapshot)
        old_state = (
            line.audio_duration,
            line.audio_status,
            line.audio_similarity,
            line.audio_transcribed_text,
            line.audio_hallucination,
            line.audio_filename
        )

        uid = line.uid
        text = line.get_tts_text().strip()
        
        if not text:
            line.audio_status = 'EMPTY'
            # Sprawdzamy czy faktycznie coś się zmieniło
            modified = old_state != (line.audio_duration, line.audio_status, line.audio_similarity, line.audio_transcribed_text, line.audio_hallucination, line.audio_filename)
            return line, modified
        
        # Szukanie pliku
        audio_file = None
        ext = ""
        
        # Optymalizacja: jeśli mamy już nazwę pliku, sprawdź najpierw ją
        if line.audio_filename:
            from app.io import get_audio_dir
            adir = get_audio_dir()
            if adir:
                potential = adir / line.audio_filename
                if potential.exists():
                    audio_file = potential
                    ext = audio_file.suffix.lower().lstrip('.')
        
        if not audio_file:
            audio_file, ext = VerificationManager._find_audio_for_uid(uid)
        
        if not audio_file:
            line.audio_status = 'MISSING'
            line.audio_duration = 0.0
            line.audio_filename = ''
            modified = old_state != (line.audio_duration, line.audio_status, line.audio_similarity, line.audio_transcribed_text, line.audio_hallucination, line.audio_filename)
            return line, modified
            
        line.audio_filename = audio_file.name
        line.audio_format = ext
        
        # Weryfikacja Długości
        if verify_duration:
            # Skip if already have duration and not forced
            if not force_refresh and line.audio_duration > 0:
                duration = line.audio_duration
                # Ustaw status na OK jeśli był PENDING/MISSING ale plik jest
                if line.audio_status in ['PENDING', 'MISSING']:
                    line.audio_status = 'OK'
            else:
                duration = VerificationManager._get_audio_duration(audio_file, ext, ffprobe_path)
                
                if duration <= 0:
                    status = 'ERROR' if duration < 0 else 'EMPTY'
                    line.audio_duration = 0.0
                    line.audio_status = status
                    modified = old_state != (line.audio_duration, line.audio_status, line.audio_similarity, line.audio_transcribed_text, line.audio_hallucination, line.audio_filename)
                    return line, modified
                line.audio_duration = round(duration, 3)
                line.audio_status = 'OK'
        else:
            duration = line.audio_duration
            if line.audio_status in ['PENDING', 'MISSING']:
                line.audio_status = 'OK'
        
        # 1. Weryfikacja similarity i transkrypcji via Whisper
        if verify_similarity:
            if not force_refresh and line.audio_transcribed_text:
                pass 
            else:
                try:
                    sim_result = VerificationManager.verify_similarity(line, audio_file)
                    if sim_result.get('success'):
                        line.audio_similarity = sim_result.get('similarity', 0.0)
                        line.audio_transcribed_text = sim_result.get('transcribed_text', '')
                except Exception:
                    pass

        # 2. Wykrywanie halucynacji (cisza / brzęczenie)
        if verify_hallucination:
            # Skip if already verified (not PENDING and not empty) and not forced
            # Empty string indicates it might be from an old version or not yet processed in the new system
            if not force_refresh and line.audio_hallucination not in ["PENDING", ""]:
                pass
            else:
                hallucinations = []


                ffmpeg_path = None
                if ffprobe_path:
                     potential_ffmpeg = ffprobe_path.replace('ffprobe', 'ffmpeg')
                     if os.path.exists(potential_ffmpeg):
                         ffmpeg_path = potential_ffmpeg
                
                if not ffmpeg_path:
                    ffmpeg_path = shutil.which('ffmpeg')
                    
                if ffmpeg_path:
                    silences = VerificationManager.detect_silence(audio_file, ffmpeg_path)
                    long_silences = [s for s in silences if s['duration'] > 0.7]
                    if long_silences:
                        hallucinations.append("CISZA")
                
                if line.audio_similarity > 0 and line.audio_similarity < 0.4:
                    if duration > (len(text) / 4.0 + 3.0):
                        hallucinations.append("HALU?")
                
                cps = line.calculate_cps()
                if cps > 0 and cps < 4.0 and duration > 5.0:
                    if "HALU?" not in hallucinations:
                        hallucinations.append("BARDZO WOLNO")

                line.audio_hallucination = ", ".join(hallucinations) if hallucinations else "Brak"
        
        modified = old_state != (line.audio_duration, line.audio_status, line.audio_similarity, line.audio_transcribed_text, line.audio_hallucination, line.audio_filename)
        return line, modified

    @staticmethod
    def detect_silence(file_path: Path, ffmpeg_path: str) -> List[Dict[str, float]]:
        """
        Używa ffmpeg do wykrycia fragmentów ciszy.
        """
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            # silencedetect: n = noise threshold (-40dB), d = duration threshold (1s)
            cmd = [ffmpeg_path, "-i", str(file_path), "-af", "silencedetect=n=-40dB:d=1", "-f", "null", "-"]
            
            res = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo, timeout=15)
            output = res.stderr
            
            silences = []
            starts = re.findall(r"silence_start: ([\d.]+)", output)
            ends = re.findall(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", output)
            
            for i in range(min(len(starts), len(ends))):
                silences.append({
                    'start': float(starts[i]),
                    'end': float(ends[i][0]),
                    'duration': float(ends[i][1])
                })
            return silences
        except Exception as e:
            print(f"[DEBUG] detect_silence error: {e}")
            return []

    @staticmethod
    def _find_audio_for_uid(uid: str) -> Tuple[Optional[Path], str]:
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
        with VerificationManager._model_lock:
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
            tts_text = line.get_tts_text().strip()
            
            # Oczyszczenie tekstów - usunięcie znaków specjalnych, średniki, etc.
            import re
            def clean_text(text):
                # Usunięcie znaków specjalnych oprócz spacji, zachowanie tylko liter, cyfr i spacji
                text = re.sub(r'[^\w\s]', ' ', text, flags=re.UNICODE)
                # Zamiana wielkich spacji na pojedynczą
                text = re.sub(r'\s+', ' ', text)
                return text.strip().lower()
            
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


    def add_job(self, job: VerificationJob):
        self.job_queue.put(job)
        self._start_thread_if_needed()

    def _start_thread_if_needed(self):
        if self.manager_thread is None or not self.manager_thread.is_alive():
            self.manager_thread = threading.Thread(target=self._process_queue, daemon=True)
            self.manager_thread.start()

    def cancel_current(self):
        self.cancel_event.set()
        if self.worker:
            self.worker.stop(clear_queue=True)
            self.worker = None

    def _process_queue(self):
        while not self.job_queue.empty():
            job: VerificationJob = self.job_queue.get()
            self.cancel_event.clear()
            try:
                self._run_verification_job(job)
            except Exception:
                pass
        self.manager_thread = None

    @staticmethod
    def _worker_verify_task(line: Line, index: int, ffprobe_path: str, verify_hallucination: bool, verify_similarity: bool, force_refresh: bool, adir: Path):
        """Metoda wykonywana przez workera."""
        _, modified = VerificationManager.verify_line(
            line=line,
            ffprobe_path=ffprobe_path if ffprobe_path else None,
            verify_duration=True,
            verify_hallucination=verify_hallucination,
            verify_similarity=verify_similarity,
            force_refresh=force_refresh
        )
        
        # Przygotowanie wyniku
        res = asdict(line)
        res['id'] = index
        res['text'] = line.get_tts_text()
        
        if line.audio_filename and adir:
            res['path'] = str(adir / line.audio_filename)
        else:
            res['path'] = None
            
        res['duration'] = line.audio_duration
        res['similarity'] = line.audio_similarity
        res['transcribed_text'] = line.audio_transcribed_text
        res['hallucination'] = line.audio_hallucination
        res['display_status'] = line.audio_status
        res['ext'] = line.audio_format
        
        # Dodajemy flagę modyfikacji dla UI
        res['__modified'] = modified
        
        return str(index), res, modified

    def _run_verification_job(self, job: VerificationJob):
        num_workers = max(1, job.workers)
        
        # Konfiguracja workera - zawsze restartujemy dla pewności (czyszczenie kontekstu)
        if self.worker:
            self.worker.stop(clear_queue=True)
            
        self.worker = Worker(name="VerificationWorker", num_threads=num_workers)
        
        if job.audio_dir:
            set_audio_dir(Path(job.audio_dir))
            
        current_audio_dir = get_audio_dir()
        
        tracker = BatchResultTracker(len(job.lines), job.apply_callback)
        
        for i, line in enumerate(job.lines):
            if self.cancel_event.is_set():
                break
                
            def on_task_done(result):
                ident, data, modified = result
                tracker.add_result(ident, data, modified)
                
            self.worker.add_task(
                VerificationManager._worker_verify_task,
                line=line,
                index=i+1,
                ffprobe_path=job.ffprobe or '',
                verify_hallucination=job.verify_hallucination,
                verify_similarity=job.verify_similarity,
                force_refresh=job.force_refresh,
                adir=current_audio_dir,
                on_complete=on_task_done
            )
            
        # Oczekiwanie na zakończenie
        while not tracker.is_done and not self.cancel_event.is_set():
            time.sleep(0.5)
            tracker.flush_if_needed()
            
        if self.cancel_event.is_set():
            if self.worker:
                self.worker.stop(clear_queue=True)
        else:
            tracker.finish()

