import threading
import queue
import time
import requests
import json
import os
import traceback
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple, Callable, Optional, Union, Dict, Any

from generators.google_cloud_tts import GoogleCloudTTS
from generators.elevenlabs_tts import ElevenLabsTTS
from generators.tts_base import TTSBase
from audio.audio_converter import AudioConverter
from app.utils import ready_dir_from_audio_dir
from app.worker import Worker, BatchResultTracker


@dataclass
class GenerationJob:
    project_path: str
    audio_dir: Path
    lines_to_generate: List[Tuple[str, str]]
    tts_model_name: str
    tts_config: Dict[str, Any]
    converter_config: Dict[str, Any]
    on_generate: Optional[Callable[[str, str], None]] = None


@dataclass
class ConversionJob:
    project_path: str
    audio_dir: Path
    converter_config: Dict[str, Any]


JobType = Union[GenerationJob, ConversionJob]


class GenerationManager:
    _instance: Optional['GenerationManager'] = None
    _lock = threading.Lock()

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

        self.job_queue: queue.Queue[JobType] = queue.Queue()
        self.current_job: Optional[JobType] = None
        self.manager_thread: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()  # Flaga pauzy
        self.worker: Optional[Worker] = None

        self._observers_queue: List[Callable] = []
        self._observers_progress: List[Callable] = []
        
        # State for monitoring
        self.last_progress = (0, 0, "Oczekiwanie...")

    @classmethod
    def get_instance(cls) -> 'GenerationManager':
        return cls()
        
    def is_busy(self) -> bool:
        # If cancellation is requested, consider manager not busy to allow new jobs strictly
        busy_job = self.current_job is not None and not self.cancel_event.is_set()
        return busy_job or (self.worker and self.worker._is_running)

    def get_current_progress(self):
        return self.last_progress

    def add_job(self, job: JobType):
        self.job_queue.put(job)
        print(f"Dodano zadanie do kolejki: {job.project_path}")
        self._notify_queue_observers()
        self._start_thread_if_needed()

    def remove_job(self, project_path: str) -> bool:
        removed = False
        with self.job_queue.mutex:
            current_jobs = list(self.job_queue.queue)
            new_jobs = []
            for job in current_jobs:
                if job.project_path == project_path:
                    removed = True
                else:
                    new_jobs.append(job)
            if removed:
                self.job_queue.queue.clear()
                for job in new_jobs:
                    self.job_queue.queue.append(job)
        if removed:
            print(f"Usunięto zadanie {project_path} z kolejki.")
            self._notify_queue_observers()
        return removed

    def cancel_current_job(self):
        if self.current_job:
            print("Wysyłanie sygnału zatrzymania...")
            self.cancel_event.set()
            if self.worker:
                self.worker.stop(clear_queue=True)
        else:
            print("Brak bieżącego zadania do zatrzymania.")

    def pause_current_job(self):
        """Pauzuje aktualne zadanie."""
        self.pause_event.set()
        if self.worker:
            self.worker.pause()
        print("Zadanie wstrzymane.")

    def resume_current_job(self):
        """Wznawia aktualne zadanie."""
        self.pause_event.clear()
        if self.worker:
            self.worker.resume()
        print("Zadanie wznowione.")

    def _start_thread_if_needed(self):
        if self.manager_thread is None or not self.manager_thread.is_alive():
            print("Uruchamianie wątku menedżera...")
            self.manager_thread = threading.Thread(target=self._process_queue, daemon=True)
            self.manager_thread.start()

    def _process_queue(self):
        while not self.job_queue.empty():
            self.current_job = self.job_queue.get()
            self.cancel_event.clear()
            self.pause_event.clear()
            self._notify_queue_observers()

            try:
                if isinstance(self.current_job, GenerationJob):
                    print(f"Rozpoczynam zadanie generowania: {self.current_job.project_path}")
                    self._execute_tts_job(self.current_job)
                elif isinstance(self.current_job, ConversionJob):
                    print(f"Rozpoczynam zadanie konwersji: {self.current_job.project_path}")
                    self._execute_convert_job(self.current_job)

            except InterruptedError:
                print(f"Zadanie {self.current_job.project_path} zatrzymane przez użytkownika.")
                self._notify_progress(0, 1, "Zadanie zatrzymane.")
            except Exception as e:
                print(f"Błąd krytyczny w zadaniu {self.current_job.project_path}: {e}")
                traceback.print_exc() # Pokaż pełny stack trace w konsoli
                self._notify_progress(0, 1, f"Błąd: {e}")

            self.current_job = None
            self._notify_queue_observers()

        print("Kolejka zadań pusta. Zatrzymuję wątek menedżera.")
        self.manager_thread = None

    def register_queue_observer(self, callback: Callable):
        if callback not in self._observers_queue:
            self._observers_queue.append(callback)

    def unregister_queue_observer(self, callback: Callable):
        if callback in self._observers_queue:
            self._observers_queue.remove(callback)

    def register_progress_observer(self, callback: Callable):
        if callback not in self._observers_progress:
            self._observers_progress.append(callback)

    def unregister_progress_observer(self, callback: Callable):
        if callback in self._observers_progress:
            self._observers_progress.remove(callback)

    def _notify_queue_observers(self):
        jobs = list(self.job_queue.queue)
        for callback in self._observers_queue:
            callback(self.current_job, jobs)

    def _notify_progress(self, current: int, total: int, message: str):
        self.last_progress = (current, total, message)
        for callback in self._observers_progress:
            callback(current, total, message)

    def _notify_indeterminate(self, message: str):
        self.last_progress = (-1, -1, message)
        for callback in self._observers_progress:
            callback(-1, -1, message)

    # --- Logika wykonywania zadań ---

    @staticmethod
    def _worker_tts_task(identifier, text, job, tts_model_instance):
        """Statyczna metoda workera dla TTS."""
        output_path = job.audio_dir / f"output1 ({identifier}).wav"
        
        try:
            model_name_lower = job.tts_model_name.lower()

            if model_name_lower in ['xtts', 'stylish', 'piper']:
                GenerationManager._call_local_api_static(tts_model_instance, text, str(output_path), job.tts_config)
            
            elif isinstance(tts_model_instance, TTSBase):
                tts_model_instance.tts(text, str(output_path))
            else:
                raise TypeError(f"Nieznany typ instancji modelu: {type(tts_model_instance)}")

            # Powiadomienie o sukcesie (zwracamy wynik)
            return (identifier, str(output_path))
            
        except Exception as e:
            raise e

    @staticmethod
    def _call_local_api_static(tts_model: dict, text: str, output_file: str, config: dict):
        # Statyczna wersja _call_local_api
        api_url = tts_model['url']
        session = tts_model['session']
        payload = {"text": text, "output_file": output_file}

        if "xtts" in api_url.lower():
            payload["voice_file"] = config.get('xtts_voice_path', '')
        if "piper" in api_url.lower():
            payload["voice_file"] = config.get('piper_model_path', '')

        try:
            response = session.post(api_url, json=payload, timeout=90)
            response.raise_for_status()
            try:
                response_data = response.json()
                if not response_data.get("output_file") and response_data.get("error"):
                     raise ConnectionError(f"API Error Message: {response_data.get('error')}")
            except json.JSONDecodeError:
                pass
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Błąd połączenia z API ({api_url}): {e}")

    def _execute_tts_job(self, job: GenerationJob):
        print(f"DEBUG: Konfiguracja modelu: {job.tts_model_name}")
        self._notify_progress(0, 1, f"Ładowanie modelu {job.tts_model_name}...")

        # 1. Konfiguracja workera
        if self.worker:
            self.worker.stop(clear_queue=True)
        self.worker = Worker(name="TTSWorker", num_threads=1) # TTS models are mostly sequential or resource heavy

        # 1a. Ładowanie modelu
        try:
            tts_model_instance = self._load_tts_model(job.tts_model_name, job.tts_config)
            if tts_model_instance is None:
                raise ValueError("Model zwrócił None przy ładowaniu.")
        except Exception as e:
            print(f"DEBUG ERROR: Błąd ładowania modelu: {e}")
            self._notify_progress(0, 1, f"Błąd ładowania modelu: {e}")
            return

        if self.cancel_event.is_set():
            raise InterruptedError()

        total_to_gen = len(job.lines_to_generate)
        print(f"DEBUG: Liczba linii do wygenerowania: {total_to_gen}")

        if total_to_gen == 0:
            self._notify_progress(1, 1, "Brak linii do wygenerowania.")
            print("DEBUG: Lista linii jest pusta. Kończę zadanie.")
            return

        self._notify_progress(0, total_to_gen, f"Rozpoczynam generowanie {total_to_gen} linii...")

        # 2. Zlecanie zadań
        tracker = BatchResultTracker(total_to_gen, flush_interval=1.0)
        tracker.callback = lambda res: self._notify_progress(
            tracker.processed, tracker.total, f"Generowanie... ({tracker.processed}/{tracker.total})"
        )

        for identifier, text in job.lines_to_generate:
            if self.cancel_event.is_set():
                break

            def on_done(res):
                ident, path = res
                tracker.add_result(ident, path, is_modified=True)
                if getattr(job, 'on_generate', None):
                    job.on_generate(ident, path)
            
            def on_error(err):
                # Identifier is tricky to pass to error handling without partial/closure, 
                # but worker loop prints log. We just need to tick the tracker.
                tracker.add_result(identifier, None, is_modified=False) # Tratujemy jako przetworzone (z błędem)
                print(f"Błąd generowania dla {identifier}: {err}")

            self.worker.add_task(
                GenerationManager._worker_tts_task,
                identifier=identifier,
                text=text,
                job=job,
                tts_model_instance=tts_model_instance,
                on_complete=on_done,
                on_error=on_error
            )
            
        # 3. Oczekiwanie
        while not tracker.is_done and not self.cancel_event.is_set():
            time.sleep(0.5)
            
        if self.cancel_event.is_set():
            if self.worker:
                self.worker.stop(clear_queue=True)
            raise InterruptedError()

        if self.worker:
            self.worker.stop()

        self._notify_progress(total_to_gen, total_to_gen, "Zakończono.")
        print("DEBUG: Zadanie generowania zakończone sukcesem.")

    @staticmethod
    def _worker_convert_task_static(input_file, output_file, filter_settings, out_format):
        try:
            from audio.audio_converter import AudioConverter
            conv = AudioConverter(filter_settings=filter_settings, out_format=out_format)
            conv.parse_ogg(input_file, output_file)
            return True, None
        except Exception as e:
            return False, str(e)

    def _execute_convert_job(self, job: ConversionJob):
        self._notify_indeterminate("Skanowanie plików...")
        
        # 1. Konfiguracja workera
        if self.worker:
            self.worker.stop(clear_queue=True)
            self.worker = None

        try:
             workers_count = int(job.converter_config.get("conversion_workers", 4))
        except:
             workers_count = 4

        self.worker = Worker(name="ConversionWorker", num_threads=workers_count)

        # 2. Skanowanie plików
        audio_dir = job.audio_dir
        output_dir = ready_dir_from_audio_dir(audio_dir)
        os.makedirs(output_dir, exist_ok=True)

        converter_cfg = job.converter_config
        out_fmt = converter_cfg.get("audio_output_format", "mp3")
        filters = converter_cfg.get("ffmpeg_filters", {})
        
        temp_converter = AudioConverter(filter_settings=filters, out_format=out_fmt)

        tasks = []
        try:
            for filename in os.listdir(audio_dir):
                if filename.lower().endswith((".wav", ".ogg", ".mp3")):
                    if filename.lower().endswith(".temp.ogg"):
                        continue
                    
                    input_path = os.path.join(audio_dir, filename)
                    output_path = temp_converter.build_output_file_path(filename, str(output_dir), out_fmt)
                    
                    if os.path.exists(output_path):
                        continue
                        
                    tasks.append((input_path, output_path))
        except Exception as e:
             self._notify_progress(0, 1, f"Błąd skanowania katalogu: {e}")
             return

        total_tasks = len(tasks)
        if total_tasks == 0:
             self._notify_progress(1, 1, "Brak plików do konwersji lub wszystkie gotowe.")
             return

        self._notify_progress(0, total_tasks, f"Rozpoczynam konwersję {total_tasks} plików...")

        # 3. Zlecanie zadań
        # Zgodnie z wymaganiem: aktualizacja progress baru co 5 sekund
        tracker = BatchResultTracker(total_tasks, flush_interval=5.0)
        tracker.callback = lambda res: self._notify_progress(
            tracker.processed, tracker.total, f"Konwertowanie... ({tracker.processed}/{tracker.total})"
        )
        
        for inp, outp in tasks:
            if self.cancel_event.is_set():
                break
                
            def on_done_corrected(worker_res):
                # worker_res is return from _worker_convert_task_static -> (success, error)
                tracker.add_result(outp, {"success": worker_res[0], "error": worker_res[1]})

            self.worker.add_task(
                GenerationManager._worker_convert_task_static,
                input_file=inp, 
                output_file=outp,
                filter_settings=filters,
                out_format=out_fmt,
                on_complete=on_done_corrected
            )

        # 4. Oczekiwanie
        while not tracker.is_done and not self.cancel_event.is_set():
            time.sleep(0.5)
            
        if self.cancel_event.is_set():
            if self.worker:
                self.worker.stop(clear_queue=True)
            raise InterruptedError("Konwersja anulowana przez użytkownika.")
            
        if self.worker:
            self.worker.stop()

        self._notify_progress(total_tasks, total_tasks, "Zakończono konwersję.")

    def _load_tts_model(self, model_name: str, config: dict) -> Union[Dict, TTSBase, None]:
        print(f"DEBUG: _load_tts_model wywołane dla: {model_name}")
        
        # Normalizacja nazwy do małych liter dla łatwiejszego porównania
        m_name = model_name.lower()

        if m_name == 'xtts':
            api_url = config.get('local_api_url')
            if not api_url:
                raise ValueError("Brak URL dla XTTS API w ustawieniach (Globalne).")
            print(f"DEBUG: XTTS URL: {api_url}")
            session = requests.Session()
            session.headers.update({'Content-Type': 'application/json'})
            return {'url': api_url.rstrip('/') + '/xtts/tts', 'session': session}

        elif m_name == 'stylish':
            api_url = config.get('local_api_url')
            if not api_url:
                raise ValueError("Brak URL dla Stylish API w ustawieniach (Globalne).")
            print(f"DEBUG: Stylish URL: {api_url}")
            session = requests.Session()
            session.headers.update({'Content-Type': 'application/json'})
            # Ważne: endpoint dla stylish to zazwyczaj /stylish/tts
            return {'url': api_url.rstrip('/') + '/stylish/tts', 'session': session}

        elif m_name == 'elevenlabs':
            api_key = config.get('elevenlabs_api_key')
            voice_id = config.get('elevenlabs_voice_id')
            if not api_key or not voice_id:
                raise ValueError("Brak API Key lub Voice ID dla ElevenLabs.")
            return ElevenLabsTTS(api_key=api_key, voice_id=voice_id)

        elif 'google' in m_name: # Google Cloud TTS
            creds_path = config.get('google_credentials_path')
            voice_name = config.get('google_voice_name')
            if not creds_path or not Path(creds_path).exists():
                raise ValueError("Nieprawidłowa ścieżka do credentials Google TTS.")
            return GoogleCloudTTS(credentials_path=creds_path, voice_name=voice_name)

        elif m_name == 'piper':
            api_url = config.get('local_api_url')
            if not api_url:
                raise ValueError("Brak URL dla Piper API w ustawieniach (Globalne).")
            print(f"DEBUG: Piper URL: {api_url}")
            session = requests.Session()
            session.headers.update({'Content-Type': 'application/json'})
            return {'url': api_url.rstrip('/') + '/piper/tts', 'session': session}

        raise ValueError(f"Nieznany model TTS: {model_name}")

