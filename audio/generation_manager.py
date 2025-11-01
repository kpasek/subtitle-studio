# audio/generation_manager.py
import shutil
import subprocess
import sys
import threading
import queue
import requests
import json
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple, Callable, Optional, Union, Dict, Any

# Importy logiki TTS (muszą być dostępne dla wątku)
from generators.google_cloud_tts import GoogleCloudTTS
from generators.elevenlabs_tts import ElevenLabsTTS
from generators.tts_base import TTSBase


@dataclass
class GenerationJob:
    """Przechowuje wszystkie dane potrzebne do zadania generowania TTS."""
    project_path: str  # Dla wyświetlania w UI
    audio_dir: Path
    lines_to_generate: List[Tuple[str, str]]  # (identifier, text)
    tts_model_name: str
    tts_config: Dict[str, Any]
    converter_config: Dict[str, Any]



JobType = Union[GenerationJob]


class GenerationManager:
    """
    Singleton zarządzający globalną kolejką generowania i konwersji audio
    w osobnym wątku.
    """
    _instance: Optional['GenerationManager'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Zapobiegaj wielokrotnej inicjalizacji
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        self.job_queue: queue.Queue[JobType] = queue.Queue()
        self.current_job: Optional[JobType] = None
        self.manager_thread: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()

        # Obserwatorzy UI
        self._observers_queue: List[Callable] = []
        self._observers_progress: List[Callable] = []

    @classmethod
    def get_instance(cls) -> 'GenerationManager':
        """Zwraca instancję singletona."""
        return cls()

    # --- Zarządzanie zadaniami ---

    def add_job(self, job: JobType):
        """Dodaje nowe zadanie do kolejki i uruchamia wątek, jeśli nie działa."""
        self.job_queue.put(job)
        print(f"Dodano zadanie do kolejki: {job.project_path}")
        self._notify_queue_observers()
        self._start_thread_if_needed()

    def remove_job(self, project_path: str) -> bool:
        """Usuwa zadanie z kolejki (ale nie bieżące). Poprawiona wersja bezpieczna wątkowo."""
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
                    # Bezpośrednie dodanie do deque
                    self.job_queue.queue.append(job)

        if removed:
            print(f"Usunięto zadanie {project_path} z kolejki.")
            self._notify_queue_observers()
        return removed

    def cancel_current_job(self):
        """Ustawia flagę zatrzymania dla bieżącego zadania."""
        if self.current_job:
            print("Wysyłanie sygnału zatrzymania...")
            self.cancel_event.set()
        else:
            print("Brak bieżącego zadania do zatrzymania.")

    # --- Zarządzanie wątkiem ---

    def _start_thread_if_needed(self):
        """Uruchamia wątek menedżera, jeśli nie jest aktywny."""
        if self.manager_thread is None or not self.manager_thread.is_alive():
            print("Uruchamianie wątku menedżera...")
            self.manager_thread = threading.Thread(
                target=self._process_queue, daemon=True)
            self.manager_thread.start()

    def _process_queue(self):
        """Główna pętla wątku przetwarzającego zadania."""
        while not self.job_queue.empty():
            self.current_job = self.job_queue.get()
            self.cancel_event.clear()
            self._notify_queue_observers()

            try:
                if isinstance(self.current_job, GenerationJob):
                    print(
                        f"Rozpoczynam zadanie generowania: {self.current_job.project_path}")
                    self._execute_tts_job(self.current_job)

            except InterruptedError:
                print(f"Zadanie {self.current_job.project_path} zatrzymane.")
                self._notify_progress(0, 1, "Zadanie zatrzymane.")
            except Exception as e:
                print(
                    f"Błąd krytyczny w zadaniu {self.current_job.project_path}: {e}")
                self._notify_progress(0, 1, f"Błąd: {e}")

            self.current_job = None
            self._notify_queue_observers()

        print("Kolejka zadań pusta. Zatrzymuję wątek menedżera.")
        self.manager_thread = None

    # --- Obserwatorzy UI ---

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
        # Specjalny sygnał dla paska postępu
        for callback in self._observers_progress:
            callback(-1, -1, message)

    # --- Logika wykonywania zadań (przeniesiona z gui.py) ---

    def _execute_tts_job(self, job: GenerationJob):
        """Wykonuje pełne zadanie generowania TTS."""

        self._notify_progress(
            0, 1, f"Ładowanie modelu {job.tts_model_name}...")

        try:
            tts_model_instance = self._load_tts_model(
                job.tts_model_name, job.tts_config)
            if tts_model_instance is None:
                raise ValueError("Nie udało się załadować modelu TTS.")
        except Exception as e:
            self._notify_progress(0, 1, f"Błąd ładowania modelu: {e}")
            return

        if self.cancel_event.is_set():
            raise InterruptedError()

        total_to_gen = len(job.lines_to_generate)
        for i, (identifier, text) in enumerate(job.lines_to_generate):
            if self.cancel_event.is_set():
                raise InterruptedError()

            self._notify_progress(
                i, total_to_gen, f"Generowanie TTS... ({i+1}/{total_to_gen})")

            # Cel dla modeli TTS
            output_path = job.audio_dir / f"output1 ({identifier}).wav"

            try:
                if job.tts_model_name in ['XTTS', 'STylish']:
                    self._call_local_api(tts_model_instance, text, str( # type: ignore
                        output_path), job.tts_config)
                elif isinstance(tts_model_instance, TTSBase):
                    tts_model_instance.tts(text, str(output_path))
                else:
                    raise TypeError("Niespodziewany typ modelu TTS.")
            except Exception as e:
                print(f"Błąd generowania linii {identifier}: {e}")
                self._notify_progress(
                    i, total_to_gen, f"Błąd linii {identifier}: {e}")
                # Kontynuuj z następną linią
                continue

        if self.cancel_event.is_set():
            raise InterruptedError()

        self._notify_progress(total_to_gen, total_to_gen, "Zakończono.")

        if self.cancel_event.is_set():
            raise InterruptedError()

        self._notify_progress(1, 1, "Zakończono konwersję.")

    def _load_tts_model(self, model_name: str, config: dict) -> Union[Dict, TTSBase, None]:
        """Tworzy instancję modelu TTS na podstawie konfiguracji."""

        if model_name == 'XTTS':
            api_url = config.get('local_api_url')
            if not api_url:
                raise ValueError(
                    "Brak URL dla XTTS API w konfiguracji zadania.")
            session = requests.Session()
            session.headers.update({'Content-Type': 'application/json'})
            return {'url': api_url.rstrip('/') + '/xtts/tts', 'session': session}

        if model_name == 'STylish':
            api_url = config.get('local_api_url')
            if not api_url:
                raise ValueError(
                    "Brak URL dla STylish API w konfiguracji zadania.")
            session = requests.Session()
            session.headers.update({'Content-Type': 'application/json'})
            return {'url': api_url.rstrip('/') + '/stylish/tts', 'session': session}

        elif model_name == 'ElevenLabs':
            api_key = config.get('elevenlabs_api_key')
            voice_id = config.get('elevenlabs_voice_id')
            if not api_key or not voice_id:
                raise ValueError("Brak klucza API lub Voice ID ElevenLabs.")
            return ElevenLabsTTS(api_key=api_key, voice_id=voice_id)

        elif model_name == 'Google Cloud TTS':
            creds_path = config.get('google_credentials_path')
            voice_name = config.get('google_voice_name')
            if not creds_path or not Path(creds_path).exists():
                raise ValueError(
                    "Nieprawidłowa ścieżka do credentials Google TTS.")
            return GoogleCloudTTS(credentials_path=creds_path, voice_name=voice_name)

        raise ValueError(f"Nieznany model TTS: {model_name}")

    def _call_local_api(self, tts_model: dict, text: str, output_file: str, config: dict):
        """Wywołuje lokalne API (np. XTTS)."""
        api_url = tts_model['url']
        session = tts_model['session']
        payload = {"text": text, "output_file": output_file}

        if "xtts" in api_url.lower():
            payload["voice_file"] = config.get('xtts_voice_path', '')

        try:
            response = session.post(api_url, json=payload, timeout=90)
            response.raise_for_status()
            response_data = response.json()
            if not response_data.get("output_file", ""):
                raise ConnectionError(
                    f"API Error: {response_data.get('error', response.text)}")
        except requests.exceptions.RequestException as e:
            raise ConnectionError(
                f"Błąd połączenia z Local API ({api_url}): {e}")

        """Uruchamia konwerter audio."""

        workers = config.get("conversion_workers", 4)
        speed = config.get("base_audio_speed", 1.1)
        filters = config.get("ffmpeg_filters", {})
        audio_dir = config.get("audio_path", {})

        if getattr(sys, 'frozen', False):
            exe_path = "converter.exe"  # type: ignore
        else:
            exe_path = Path(__file__).parent / "converter.py"
        cmd = [
            exe_path,
            "--path", str(audio_dir),
            "--workers", str(workers),
            "--speed", str(speed),
            "--filters", json.dumps(filters)
        ]
        
        try:
            if sys.platform.startswith("win"):
                # Uruchom nowy terminal (cmd)
                subprocess.Popen(["start", "cmd", "/K"] + cmd, shell=True)
            elif sys.platform.startswith("linux"):
                # Uruchom w nowym terminalu (Linux – obsługa GNOME/KDE)
                term_cmd = shutil.which(
                    "x-terminal-emulator") or shutil.which("gnome-terminal") or shutil.which("konsole")
                if term_cmd:
                    subprocess.Popen([term_cmd, "--"] + cmd)
                else:
                    subprocess.Popen(cmd)
            elif sys.platform == "darwin":
                # macOS – otwarcie w Terminal.app
                subprocess.Popen(["open", "-a", "Terminal.app"] + cmd)
            else:
                subprocess.Popen(cmd)
        except Exception as e:
            print("Błąd uruchamiania konwersji", str(e))
