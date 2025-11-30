import threading
import queue
import requests
import json
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple, Callable, Optional, Union, Dict, Any

from generators.google_cloud_tts import GoogleCloudTTS
from generators.elevenlabs_tts import ElevenLabsTTS
from generators.tts_base import TTSBase
from audio.audio_converter import AudioConverter


@dataclass
class GenerationJob:
    """
    lines_to_generate: Lista krotek (UUID, text).
    """
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
        if hasattr(self, '_initialized'): return
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
        self._notify_queue_observers()
        self._start_thread_if_needed()

    def _start_thread_if_needed(self):
        if self.manager_thread is None or not self.manager_thread.is_alive():
            self.manager_thread = threading.Thread(target=self._process_queue, daemon=True)
            self.manager_thread.start()

    def _process_queue(self):
        while not self.job_queue.empty():
            self.current_job = self.job_queue.get()
            self.cancel_event.clear()
            self._notify_queue_observers()
            try:
                if isinstance(self.current_job, GenerationJob):
                    self._execute_tts_job(self.current_job)
                elif isinstance(self.current_job, ConversionJob):
                    self._execute_convert_job(self.current_job)
            except Exception as e:
                print(f"Błąd zadania: {e}")
                self._notify_progress(0, 1, f"Błąd: {e}")
            self.current_job = None
            self._notify_queue_observers()
        self.manager_thread = None

    def _execute_tts_job(self, job: GenerationJob):
        self._notify_progress(0, 1, f"Ładowanie {job.tts_model_name}...")
        try:
            model = self._load_tts_model(job.tts_model_name, job.tts_config)
            if not model: raise ValueError("Model init failed")
        except Exception as e:
            self._notify_progress(0, 1, str(e))
            return

        total = len(job.lines_to_generate)
        for i, (line_uuid, text) in enumerate(job.lines_to_generate):
            if self.cancel_event.is_set(): break
            self._notify_progress(i, total, f"Gen: {i + 1}/{total}")

            # Kluczowa zmiana: nazwa pliku zawiera UUID, nie index
            filename = f"output1 ({line_uuid}).wav"
            out_path = job.audio_dir / filename

            try:
                if isinstance(model, dict):  # API
                    self._call_local_api(model, text, str(out_path), job.tts_config)
                elif isinstance(model, TTSBase):
                    model.tts(text, str(out_path))
            except Exception as e:
                print(f"Błąd linii {line_uuid}: {e}")

        self._notify_progress(total, total, "Gotowe.")

    def _execute_convert_job(self, job: ConversionJob):
        self._notify_indeterminate("Konwertowanie...")
        # (Tu implementacja konwersji używająca AudioConverter)
        # Dla skrócenia pomijam pełną implementację AudioConvertera,
        # ale powinna być zgodna z wywołaniem w poprzednich wersjach.
        pass

    def _load_tts_model(self, name, cfg):
        # (Logika fabryki modeli bez zmian)
        if name == 'XTTS':
            return {'url': cfg['local_api_url'] + '/xtts/tts', 'session': requests.Session()}
        # ... pozostałe ...
        return None

    def _call_local_api(self, model, text, out, cfg):
        # (Logika wywołania API)
        pass

    # Metody notyfikacji
    def register_queue_observer(self, cb):
        self._observers_queue.append(cb)

    def register_progress_observer(self, cb):
        self._observers_progress.append(cb)

    def _notify_queue_observers(self):
        q = list(self.job_queue.queue)
        for cb in self._observers_queue: cb(self.current_job, q)

    def _notify_progress(self, c, t, m):
        for cb in self._observers_progress: cb(c, t, m)

    def _notify_indeterminate(self, m):
        for cb in self._observers_progress: cb(-1, -1, m)