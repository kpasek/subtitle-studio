import threading
import queue
import time
import uuid
import logging
from typing import Callable, Any, Optional, Dict, List
from dataclasses import dataclass, field

# Konfiguracja logowania (można dostosować do systemu logowania w aplikacji)
logger = logging.getLogger(__name__)

@dataclass
class WorkerTask:
    """Reprezentuje pojedyncze zadanie w kolejce."""
    task_id: str
    process_func: Callable[..., Any]  # Funkcja wykonująca właściwą pracę
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    on_complete: Optional[Callable[[Any], None]] = None  # Callback po sukcesie (wynik)
    on_error: Optional[Callable[[Exception], None]] = None  # Callback po błędzie
    on_progress: Optional[Callable[[int, str], None]] = None # Callback postępu (procent, status)

class Worker:
    """
    Generyczny worker do wykonywania zadań w tle na puli wątków.
    Posiada własną kolejkę, obsługuje pauzowanie i zatrzymywanie.
    """
    def __init__(self, name: str = "Worker", num_threads: int = 1):
        self.name = name
        self.num_threads = num_threads
        
        self._queue: queue.Queue = queue.Queue()
        self._threads: List[threading.Thread] = []
        self._stop_event = threading.Event()
        self._pause_event = threading.Event() # Jeśli ustawione -> zapauzowany
        
        # Stan workera
        self._is_running = False
        
        # Inicjalizacja wątków
        self._start_threads()

    def _start_threads(self):
        """Uruchamia wątki robocze."""
        self._is_running = True
        for i in range(self.num_threads):
            t = threading.Thread(target=self._worker_loop, name=f"{self.name}-Thread-{i+1}", daemon=True)
            t.start()
            self._threads.append(t)

    def add_task(self, 
                 func: Callable, 
                 *args, 
                 on_complete: Optional[Callable] = None, 
                 on_error: Optional[Callable] = None, 
                 on_progress: Optional[Callable] = None,
                 **kwargs) -> str:
        """
        Dodaje zadanie do kolejki.
        Zwraca wygenerowane ID zadania.
        """
        if self._stop_event.is_set():
            logger.warning(f"[{self.name}] Próba dodania zadania do zatrzymanego workera.")
            return ""

        task_id = str(uuid.uuid4())
        task = WorkerTask(
            task_id=task_id,
            process_func=func,
            args=args,
            kwargs=kwargs,
            on_complete=on_complete,
            on_error=on_error,
            on_progress=on_progress
        )
        
        self._queue.put(task)
        # logger.debug(f"[{self.name}] Dodano zadanie {task_id}. W kolejce: {self._queue.qsize()}")
        return task_id

    def pause(self):
        """Wstrzymuje pobieranie nowych zadań z kolejki."""
        if not self._pause_event.is_set():
            self._pause_event.set()
            logger.info(f"[{self.name}] Wstrzymano (PAUSE). Aktualne zadania zostaną dokończone.")

    def resume(self):
        """Wznawia przetwarzanie kolejki."""
        if self._pause_event.is_set():
            self._pause_event.clear()
            logger.info(f"[{self.name}] Wznowiono (RESUME).")

    def stop(self, clear_queue: bool = True):
        """
        Zatrzymuje workera.
        Jeśli clear_queue=True, usuwa wszystkie oczekujące zadania.
        """
        logger.info(f"[{self.name}] Zatrzymywanie...")
        self._stop_event.set()
        
        if clear_queue:
            with self._queue.mutex:
                self._queue.queue.clear()
            logger.info(f"[{self.name}] Kolejka wyczyszczona.")

    def _worker_loop(self):
        """Główna pętla wątku roboczego."""
        while not self._stop_event.is_set():
            # 1. Obsługa pauzy
            if self._pause_event.is_set():
                time.sleep(0.1) # Krótki sleep, żeby nie obciążać CPU pętlą while
                continue

            try:
                # 2. Pobranie zadania z timeoutem (żeby sprawdzać flagę stop/pause regularnie)
                task: WorkerTask = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # 3. Wykonanie zadania
            try:
                # Definiujemy lokalny helper, który odwoła się do callbacka z taska (jeśli istnieje)
                def local_progress(percent: int, message: str = ""):
                    if task.on_progress:
                        task.on_progress(percent, message)
                
                call_kwargs = task.kwargs.copy()
                if task.on_progress and 'progress_callback' not in call_kwargs:
                    call_kwargs['progress_callback'] = local_progress

                # Próba wywołania z wstrzykniętym callbackiem
                try:
                    result = task.process_func(*task.args, **call_kwargs)
                except TypeError as te:
                    # Fallback: Jeśli funkcja rzuciła TypeError o nieoczekiwanym argumencie, a my dodaliśmy progress_callback
                    # to próbujemy wywołać bez niego (oznacza to, że funkcja nie obsługuje raportowania postępu)
                    if 'progress_callback' in call_kwargs and "unexpected keyword argument 'progress_callback'" in str(te):
                        del call_kwargs['progress_callback']
                        result = task.process_func(*task.args, **call_kwargs)
                    else:
                        raise te
                
                if task.on_complete:
                    task.on_complete(result)
                    
            except Exception as e:
                logger.error(f"[{self.name}] Błąd w zadaniu {task.task_id}: {e}", exc_info=True)
                if task.on_error:
                    task.on_error(e)
            finally:
                self._queue.task_done()


class BatchResultTracker:
    """Klasa pomocnicza do śledzenia postępu grupy zadań i buforowania wyników."""
    def __init__(self, total_items, callback=None, flush_interval=1.0):
        self.total = total_items
        self.processed = 0
        self.modified = 0
        self.callback = callback
        self.flush_interval = flush_interval
        self.buffer = {}
        self.last_update_time = time.time()
        self.lock = threading.Lock()
        self.is_done = False
        self.errors = []
        
    def add_result(self, identifier, data, is_modified=False):
        with self.lock:
            self.processed += 1
            if is_modified:
                self.modified += 1
                
            if data:
                self.buffer[identifier] = data
            
            self.flush_if_needed()
                
            if self.processed >= self.total:
                self.is_done = True
                self.finish()

    def add_error(self, identifier, error_msg):
        with self.lock:
            self.processed += 1
            self.errors.append((identifier, error_msg))
            self.flush_if_needed()
            if self.processed >= self.total:
                self.is_done = True
                self.finish()

    def flush_if_needed(self):
        now = time.time()
        # Flush if interval passed or finished all (and have updates)
        if (now - self.last_update_time >= self.flush_interval) or (self.processed >= self.total and self.processed > 0):
            self._flush()
            self.last_update_time = now
            
    def finish(self):
        self._flush()
        if self.callback:
            try:
                # Przekazujemy info o błędach jeśli takie były
                final_status = {'__done': True}
                if self.errors:
                    final_status['__errors'] = self.errors
                self.callback(final_status)
            except:
                pass

    def _flush(self):
        if not self.buffer:
            return
            
        if self.callback:
            try:
                self.callback(self.buffer.copy())
            except:
                pass
        self.buffer.clear()


    def get_queue_size(self) -> int:
        return self._queue.qsize()

    def is_busy(self) -> bool:
        """Zwraca True jeśli kolejka nie jest pusta lub wątki pracują (uproszczone)."""
        return not self._queue.empty()
