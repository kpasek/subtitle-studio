import time
import random
import logging
from app.worker import Worker

# Konfiguracja logowania, żeby widzieć co się dzieje
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')

def dlugie_zadanie(numer: int, czas_trwania: float, progress_callback=None):
    """Przykładowa funkcja przetwarzająca."""
    logging.info(f"Start zadania #{numer}")
    steps = 10
    step_time = czas_trwania / steps
    
    for i in range(steps):
        time.sleep(step_time)
        percent = (i + 1) * 10
        if progress_callback:
            progress_callback(percent, f"Przetwarzanie kroku {i+1}/10")
            
    logging.info(f"Koniec zadania #{numer}")
    return f"Wynik #{numer}"

def on_result(result):
    logging.info(f"Otrzymano wynik: {result}")

def on_progress_ui(percent, status):
    # Tutaj normalnie aktualizowalibyśmy pasek postępu w UI
    logging.info(f"               [UI UPDATE] Postęp: {percent}% - status: {status}")

def run_demo():
    # 1. Tworzymy workera z 2 wątkami
    worker = Worker(name="DemoWorker", num_threads=2)
    
    logging.info("--- Wrzucanie 5 zadań na kolejkę ---")
    
    # 2. Dodajemy zadania
    for i in range(1, 6):
        worker.add_task(
            dlugie_zadanie, 
            i, 
            random.uniform(1.0, 3.0), # Losowy czas trwania 1-3s
            on_complete=on_result,
            on_progress=on_progress_ui
        )

    logging.info("Czekamy 5 sekund, aż zadania ruszą...")
    time.sleep(5)
    
    logging.info("--- PAUZA (aktualne zadania się dokończą, nowe nie będą brane) ---")
    worker.pause()
    
    logging.info("Dodaję zadanie nr 6 i 7 w czasie pauzy (powinny czekać)")
    worker.add_task(dlugie_zadanie, 6, 1.0, on_complete=on_result)
    worker.add_task(dlugie_zadanie, 7, 1.0, on_complete=on_result)
    
    time.sleep(3)
    logging.info(f"Rozmiar kolejki podczas pauzy: {worker.get_queue_size()}")
    
    logging.info("--- WZNOWIENIE ---")
    worker.resume()
    time.sleep(4)
    
    logging.info("--- STOP I CZYSZCZENIE ---")
    # Dodajmy dużo szybko, żeby zobaczyć czy wyczyści
    for i in range(20, 30):
        worker.add_task(dlugie_zadanie, i, 1.0)
    logging.info(f"Rozmiar kolejki przed stopem: {worker.get_queue_size()}")
    
    worker.stop(clear_queue=True)
    logging.info("Worker zatrzymany.")

if __name__ == "__main__":
    run_demo()
