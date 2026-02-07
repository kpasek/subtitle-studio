import threading
import queue
import os
import time
import tempfile
import uuid
import json
import multiprocessing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any


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


# --- worker entry (copied from prior implementation) ---
def _verification_process_entry(audio_dir: str, lines_texts: list, out_file: str, ffprobe_path: str, force_refresh: bool, ignore_short: bool, worker_idx: int = 0, total_workers: int = 1):
    import json
    import subprocess
    from pathlib import Path
    from collections import Counter

    audio_dir_p = Path(audio_dir) if audio_dir else Path('.')
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
        tts = (text or '').strip()
        entry = {'id': i+1, 'text': tts, 'duration': 0.0, 'cps': 0.0, 'raw_status': 'PENDING', 'path': None, 'ext': '', 'display_status': 'PENDING'}
        if not tts:
            results[ident] = entry
            write_atomic(results)
            continue

        audio_file = None
        found_ext = ''
        candidates = [
            (audio_dir_p / f"output1 ({ident}).wav", 'wav'),
            (audio_dir_p / f"output1 ({ident}).mp3", 'mp3'),
            (audio_dir_p / 'ready' / f"output1 ({ident}).ogg", 'ogg'),
            (audio_dir_p / 'ready' / f"output1 ({ident}).mp3", 'mp3')
        ]
        for p, ext in candidates:
            if p.exists():
                audio_file = p
                found_ext = ext
                break

        duration = 0.0
        if audio_file and ffprobe_path:
            try:
                res = subprocess.run([ffprobe_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_file)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    duration = float(res.stdout.strip())
                else:
                    duration = -1.0
            except Exception:
                duration = -1.0

        raw_status = 'OK'
        cps = 0.0
        if not audio_file:
            raw_status = 'MISSING'
        elif duration < 0:
            raw_status = 'ERROR'
        elif duration == 0:
            raw_status = 'EMPTY'
        else:
            stats = Counter(tts.strip('.?!'))
            short = stats[','] + stats['-']
            long = stats['.'] + stats['!'] + stats['?']
            pauses = (short * 0.4) + (long * 0.6)
            try:
                cps = len(tts) / (duration - pauses)
            except Exception:
                cps = 0.0

        entry.update({'duration': duration, 'cps': cps, 'raw_status': raw_status, 'path': str(audio_file) if audio_file else None, 'ext': found_ext})

        if raw_status != 'OK':
            entry['display_status'] = raw_status
        else:
            if ignore_short and len(tts) < 5:
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

        results[ident] = entry
        write_atomic(results)
    write_atomic(results)
