import threading
import time
import shutil
import os
import subprocess
from pathlib import Path
from queue import Queue, Empty
from typing import List, Callable, Dict, Union

from app.entity import SubtitleLine
from generators.tts_base import TTSBase


class GenerationJob:
    def __init__(self, project_path: str, audio_dir: Path, lines_to_generate: List[tuple],
                 tts_model_name: str, tts_config: dict, converter_config: dict):
        self.project_path = project_path
        self.audio_dir = audio_dir
        self.lines_to_generate = lines_to_generate
        self.tts_model_name = tts_model_name
        self.tts_config = tts_config
        self.converter_config = converter_config
        self.total_lines = len(lines_to_generate)
        self.processed_lines = 0
        self.is_conversion = False


class ConversionJob:
    def __init__(self, project_path: str, audio_dir: Path, converter_config: dict):
        self.project_path = project_path
        self.audio_dir = audio_dir
        self.converter_config = converter_config
        self.is_conversion = True
        self.total_files = 0
        self.processed_files = 0

JobType = Union[GenerationJob, ConversionJob]

class GenerationManager:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = GenerationManager()
        return cls._instance

    def __init__(self):
        self.job_queue = Queue()
        self.current_job = None
        self.is_processing = False
        self.stop_flag = False
        self.observers: List[Callable] = []

        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def add_job(self, job):
        self.job_queue.put(job)
        self._notify_observers()

    def cancel_current_job(self):
        self.stop_flag = True
        self._notify_observers(status="Anulowanie...")

    def register_queue_observer(self, callback: Callable):
        if callback not in self.observers:
            self.observers.append(callback)

    def unregister_queue_observer(self, callback: Callable):
        if callback in self.observers:
            self.observers.remove(callback)

    def _notify_observers(self, status=None):
        queue_size = self.job_queue.qsize()
        job_info = None

        if self.current_job:
            if self.current_job.is_conversion:
                total = getattr(self.current_job, 'total_files', 1)
                processed = getattr(self.current_job, 'processed_files', 0)
            else:
                total = self.current_job.total_lines
                processed = self.current_job.processed_lines

            job_info = {
                'type': 'Konwersja' if self.current_job.is_conversion else 'TTS',
                'progress': processed / total if total > 0 else 0,
                'current': processed,
                'total': total,
                'desc': status if status else ("Przetwarzanie..." if self.is_processing else "Oczekiwanie")
            }

        for cb in self.observers:
            try:
                cb(self.is_processing, job_info, queue_size)
            except Exception:
                pass

    def _worker_loop(self):
        while True:
            try:
                job = self.job_queue.get(timeout=1)
                self.current_job = job
                self.is_processing = True
                self.stop_flag = False
                self._notify_observers(status="Start zadania")

                if isinstance(job, GenerationJob):
                    self._process_tts_job(job)
                elif isinstance(job, ConversionJob):
                    self._process_conversion_job(job)

                self.current_job = None
                self.is_processing = False
                self.job_queue.task_done()
                self._notify_observers(status="Gotowy")

            except Empty:
                time.sleep(0.5)
            except Exception as e:
                print(f"Worker Error: {e}")
                self.current_job = None
                self.is_processing = False
                self._notify_observers(status=f"Błąd: {e}")

    def _process_tts_job(self, job: GenerationJob):
        try:
            generator = self._get_tts_generator(job.tts_model_name, job.tts_config)
        except Exception as e:
            print(f"Błąd inicjalizacji TTS: {e}")
            return

        for i, (uuid, text) in enumerate(job.lines_to_generate):
            if self.stop_flag: break

            job.processed_lines = i
            self._notify_observers(status=f"Generowanie: {uuid}")
            output_path = job.audio_dir / f"output1 ({uuid}).wav"

            try:
                if generator:
                    generator.generate(text, output_path)
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"Błąd generowania linii {uuid}: {e}")

        job.processed_lines = job.total_lines
        self._notify_observers()

    def _process_conversion_job(self, job: ConversionJob):
        # Konwersja używając FFmpeg bez otwierania okna cmd
        src_files = list(job.audio_dir.glob("output1 (*).wav"))
        job.total_files = len(src_files)
        if job.total_files == 0: return

        filters = job.converter_config.get('ffmpeg_filters', {})
        filter_str = self._build_ffmpeg_filter_str(filters)
        speed = job.converter_config.get('base_audio_speed', 1.1)

        ready_dir = job.audio_dir / "ready"
        if job.converter_config.get('clear_ready', False):
            if ready_dir.exists(): shutil.rmtree(ready_dir)
        ready_dir.mkdir(exist_ok=True)

        # Flagi startupinfo dla Windows aby ukryć konsolę
        si = None
        if os.name == 'nt':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTUPF_USESHOWWINDOW

        for i, src in enumerate(src_files):
            if self.stop_flag: break

            job.processed_files = i
            self._notify_observers(status=f"Konwertowanie: {src.name}")

            # Budowa komendy
            # ffmpeg -i input -filter_complex ... output

            # Prosty przykład filtra
            # Jeśli włączone out1 (normal) i out2 (speed)

            out1_path = ready_dir / (src.stem + ".ogg")

            cmd = ["ffmpeg", "-y", "-i", str(src)]

            # Aplikacja filtrów audio
            af = []
            if filter_str: af.append(filter_str)

            # Domyślne kodowanie do OGG
            cmd += ["-c:a", "libvorbis", "-q:a", "4"]

            if af:
                cmd += ["-af", ",".join(af)]

            cmd.append(str(out1_path))

            try:
                subprocess.run(cmd, startupinfo=si, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            except Exception as e:
                print(f"Conversion Error {src.name}: {e}")

        job.processed_files = job.total_files
        self._notify_observers()

    def _build_ffmpeg_filter_str(self, filters):
        # filters = { 'highpass': {'enabled': True, 'params': '...'}, ... }
        parts = []
        for key, data in filters.items():
            if data.get('enabled'):
                params = data.get('params', '')
                if params:
                    parts.append(f"{key}={params}")
                else:
                    parts.append(key)
        return ",".join(parts)

    def _get_tts_generator(self, name, config) -> TTSBase:
        # Dummy factory
        return None