import threading
import queue
import requests
import json
import os
import traceback
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple, Callable, Optional, Union, Dict, Any

# Importy logiki TTS
from generators.google_cloud_tts import GoogleCloudTTS
from generators.elevenlabs_tts import ElevenLabsTTS
from generators.tts_base import TTSBase
from audio.audio_converter import AudioConverter


@dataclass
class GenerationJob:
    project_path: str
    audio_dir: Path
    lines_to_generate: List[Tuple[str, str]]
    tts_model_name: str
    tts_config: Dict[str, Any]
    converter_config: Dict[str, Any]


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

        self._observers_queue: List[Callable] = []
        self._observers_progress: List[Callable] = []

    @classmethod
    def get_instance(cls) -> 'GenerationManager':
        return cls()

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
        else:
            print("Brak bieżącego zadania do zatrzymania.")

    def _start_thread_if_needed(self):
        if self.manager_thread is None or not self.manager_thread.is_alive():
            print("Uruchamianie wątku menedżera...")
            self.manager_thread = threading.Thread(target=self._process_queue, daemon=True)
            self.manager_thread.start()

    def _process_queue(self):
        while not self.job_queue.empty():
            self.current_job = self.job_queue.get()
            self.cancel_event.clear()
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
        for callback in self._observers_progress:
            callback(current, total, message)

    def _notify_indeterminate(self, message: str):
        for callback in self._observers_progress:
            callback(-1, -1, message)

    # --- Logika wykonywania zadań ---

    def _execute_tts_job(self, job: GenerationJob):
        print(f"DEBUG: Konfiguracja modelu: {job.tts_model_name}")
        self._notify_progress(0, 1, f"Ładowanie modelu {job.tts_model_name}...")

        # 1. Ładowanie modelu
        try:
            tts_model_instance = self._load_tts_model(job.tts_model_name, job.tts_config)
            if tts_model_instance is None:
                raise ValueError("Model zwrócił None przy ładowaniu.")
        except Exception as e:
            # KLUCZOWE: Wypisz błąd w konsoli!
            print(f"DEBUG ERROR: Błąd ładowania modelu: {e}")
            self._notify_progress(0, 1, f"Błąd ładowania modelu: {e}")
            return

        if self.cancel_event.is_set():
            raise InterruptedError()

        total_to_gen = len(job.lines_to_generate)
        print(f"DEBUG: Liczba linii do wygenerowania: {total_to_gen}")

        if total_to_gen == 0:
            print("DEBUG: Lista linii jest pusta. Kończę zadanie.")
            self._notify_progress(1, 1, "Brak linii do wygenerowania.")
            return

        # 2. Pętla generowania
        for i, (identifier, text) in enumerate(job.lines_to_generate):
            if self.cancel_event.is_set():
                raise InterruptedError()

            self._notify_progress(i, total_to_gen, f"Generowanie... ({i + 1}/{total_to_gen})")
            output_path = job.audio_dir / f"output1 ({identifier}).wav"

            try:
                # Zabezpieczenie przed różnicą wielkości liter (xtts vs XTTS, stylish vs STylish)
                model_name_lower = job.tts_model_name.lower()

                if model_name_lower in ['xtts', 'stylish']:
                    # Obsługa modeli API (dict)
                    print(f"DEBUG: Wywołanie API ({model_name_lower}) dla id={identifier}")
                    self._call_local_api(tts_model_instance, text, str(output_path), job.tts_config)
                
                elif isinstance(tts_model_instance, TTSBase):
                    # Obsługa modeli klasowych (Google, ElevenLabs)
                    tts_model_instance.tts(text, str(output_path))
                
                else:
                    raise TypeError(f"Nieznany typ instancji modelu: {type(tts_model_instance)}")

            except Exception as e:
                print(f"DEBUG ERROR: Błąd generowania linii {identifier}: {e}")
                self._notify_progress(i, total_to_gen, f"Błąd linii {identifier}: {e}")
                # Kontynuujemy z następną linią, mimo błędu
                continue

        if self.cancel_event.is_set():
            raise InterruptedError()

        self._notify_progress(total_to_gen, total_to_gen, "Zakończono.")
        print("DEBUG: Zadanie generowania zakończone sukcesem.")

    def _execute_convert_job(self, job: ConversionJob):
        self._notify_indeterminate("Rozpoczynam konwertowanie audio...")
        self._run_converter(job.audio_dir, job.converter_config)
        if self.cancel_event.is_set():
            raise InterruptedError()
        self._notify_progress(1, 1, "Zakończono konwersję.")

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

        raise ValueError(f"Nieznany model TTS: {model_name}")

    def _call_local_api(self, tts_model: dict, text: str, output_file: str, config: dict):
        api_url = tts_model['url']
        session = tts_model['session']
        payload = {"text": text, "output_file": output_file}

        # XTTS wymaga dodatkowego parametru
        if "xtts" in api_url.lower():
            payload["voice_file"] = config.get('xtts_voice_path', '')

        try:
            response = session.post(api_url, json=payload, timeout=90)
            response.raise_for_status()
            
            # Niektóre API mogą zwracać 200 OK ale z jsonem {"error": "..."}
            try:
                response_data = response.json()
                if not response_data.get("output_file") and response_data.get("error"):
                     raise ConnectionError(f"API Error Message: {response_data.get('error')}")
            except json.JSONDecodeError:
                pass # Jeśli nie JSON, a status 200, to zakładamy że ok (chyba że binary)

        except requests.exceptions.RequestException as e:
            print(f"DEBUG ERROR: Request failed to {api_url}: {e}")
            raise ConnectionError(f"Błąd połączenia z API ({api_url}): {e}")

    def _run_converter(self, audio_dir: Path, config: dict):
        try:
            filter_settings = config.get('ffmpeg_filters', {})
            default_workers = max(1, os.cpu_count() // 2 if os.cpu_count() else 4)
            max_workers = int(config.get('conversion_workers', default_workers))

            converter = AudioConverter(filter_settings=filter_settings, out_format=config.get('audio_output_format', 'mp3'))
            output_dir = audio_dir / "ready"
            os.makedirs(output_dir, exist_ok=True)

            def conversion_progress(current: int, total: int):
                if not self.cancel_event.is_set():
                    self._notify_progress(current, total, f"Konwertowanie... ({current}/{total})")

            converter.convert_dir(
                str(audio_dir),
                str(output_dir),
                max_workers=max_workers,
                progress_callback=conversion_progress,
                cancel_event=self.cancel_event
            )

        except Exception as e:
            print(f"Błąd podczas konwersji audio w menedżerze: {e}")
            raise e