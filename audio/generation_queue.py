# audio/generation_queue.py
import customtkinter as ctk
from typing import List, Optional
from audio.generation_manager import GenerationManager, JobType, GenerationJob, ConversionJob


class GenerationQueueWindow(ctk.CTkToplevel):
    """
    Okno UI do wyświetlania i zarządzania globalną kolejką
    GenerationManager.
    """

    def __init__(self, master):
        super().__init__(master)
        self.title("Kolejka generowania audio")
        self.geometry("600x450")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self.manager = GenerationManager.get_instance()
        self.manager.register_queue_observer(self._update_job_list_safe)
        self.manager.register_progress_observer(self._update_progress_safe)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.transient(master)
        self.grab_set()

        # --- Bieżące zadanie ---
        ctk.CTkLabel(self, text="Bieżące zadanie:", font=("", 14, "bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 2))

        self.lbl_current_job = ctk.CTkLabel(self, text="Brak", anchor="w")
        self.lbl_current_job.grid(row=1, column=0, sticky="ew", padx=10)

        self.progress_bar = ctk.CTkProgressBar(self, height=15)
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        self.progress_bar.set(0)

        self.lbl_progress_text = ctk.CTkLabel(
            self, text="", anchor="w", font=("", 10))
        self.lbl_progress_text.grid(row=3, column=0, sticky="ew", padx=10)

        # --- Kolejka ---
        ctk.CTkLabel(self, text="Zadania w kolejce:", font=("", 14, "bold")).grid(
            row=4, column=0, sticky="w", padx=10, pady=(10, 2))

        self.queue_frame = ctk.CTkScrollableFrame(self)
        self.queue_frame.grid(row=5, column=0, sticky="nsew", padx=10, pady=5)

        # --- Przyciski ---
        btn_frame = ctk.CTkFrame(self)
        btn_frame.grid(row=6, column=0, sticky="ew", padx=10, pady=10)

        self.btn_cancel_current = ctk.CTkButton(
            btn_frame, text="Zatrzymaj bieżące zadanie",
            command=self.manager.cancel_current_job,
            fg_color="red", hover_color="darkred")
        self.btn_cancel_current.pack(side="left", padx=5)

        self.btn_close = ctk.CTkButton(
            btn_frame, text="Zamknij okno", command=self.destroy)
        self.btn_close.pack(side="right", padx=5)

        # Inicjalne odświeżenie
        self.update_job_list(self.manager.current_job,
                             list(self.manager.job_queue.queue))

    def _update_job_list_safe(self, current_job: Optional[JobType], queued_jobs: List[JobType]):
        """Metoda bezpieczna do wywołania z innego wątku przez queue.put."""
        self.master.queue.put(
            lambda: self.update_job_list(current_job, queued_jobs))

    def _update_progress_safe(self, current: int, total: int, message: str):
        """Metoda bezpieczna do wywołania z innego wątku przez queue.put."""
        self.master.queue.put(
            lambda: self.update_progress(current, total, message))

    def update_job_list(self, current_job: Optional[JobType], queued_jobs: List[JobType]):
        """Odświeża UI na podstawie danych z menedżera."""
        if not self.winfo_exists():
            return

        # 1. Bieżące zadanie
        if current_job:
            self.lbl_current_job.configure(text=current_job.project_path)
            self.btn_cancel_current.configure(state="normal")
        else:
            self.lbl_current_job.configure(text="Brak")
            self.btn_cancel_current.configure(state="disabled")
            self.update_progress(0, 1, "Oczekuję na zadania...")

        # 2. Czyszczenie kolejki UI
        for child in self.queue_frame.winfo_children():
            child.destroy()

        # 3. Wypełnianie kolejki UI
        if not queued_jobs:
            ctk.CTkLabel(self.queue_frame,
                         text="Kolejka jest pusta.").pack(pady=5)

        for job in queued_jobs:
            job_frame = ctk.CTkFrame(self.queue_frame)
            job_frame.pack(fill="x", pady=2, padx=2)

            job_type_str = "Generowanie" if isinstance(
                job, GenerationJob) else "Konwersja"
            lbl_text = f"[{job_type_str}] {job.project_path}"

            ctk.CTkLabel(job_frame, text=lbl_text, anchor="w").pack(
                side="left", fill="x", expand=True, padx=5)

            btn_remove = ctk.CTkButton(
                job_frame, text="Usuń", width=60, fg_color="gray30",
                command=lambda p=job.project_path: self.manager.remove_job(p))
            btn_remove.pack(side="right", padx=5)

    def update_progress(self, current: int, total: int, message: str):
        """Aktualizuje pasek postępu i etykietę."""
        if not self.winfo_exists():
            return

        self.lbl_progress_text.configure(text=message)

        if current == -1 and total == -1:  # Sygnał "indeterminate"
            if self.progress_bar.cget("mode") == "determinate":
                self.progress_bar.configure(mode="indeterminate")
                self.progress_bar.start()
        else:
            if self.progress_bar.cget("mode") == "indeterminate":
                self.progress_bar.stop()
                self.progress_bar.configure(mode="determinate")

            progress_val = current / total if total > 0 else 0
            self.progress_bar.set(progress_val)

            if total > 1:  # Nie pokazuj procentów dla "Zakończono" (1/1)
                percent = int(progress_val * 100)
                self.lbl_progress_text.configure(
                    text=f"{message} ({percent}%)")

    def on_close(self):
        """Odrejestrowuje obserwatorów przed zamknięciem."""
        try:
            self.manager.unregister_queue_observer(self._update_job_list_safe)
            self.manager.unregister_progress_observer(
                self._update_progress_safe)
        except Exception as e:
            print(f"Błąd podczas odrejestrowywania obserwatorów: {e}")

        # Powiedz głównemu oknu, że jesteśmy zamknięci
        if self.master and hasattr(self.master, 'on_queue_window_close'):
            self.master.on_queue_window_close()

        self.destroy()
