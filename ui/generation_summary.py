import customtkinter as ctk
import tkinter as tk
from audio.generation_manager import GenerationManager


class GenerationSummaryWindow(ctk.CTkToplevel):
    """
    Okno dialogowe wyświetlające podsumowanie przed generowaniem lub konwersją.
    Pozwala użytkownikowi zdecydować, czy nadpisać istniejące pliki.
    Pełni także funkcję okna postępu.
    """

    def __init__(self, parent, title, total_count, existing_count, callback):
        super().__init__(parent)
        self.callback = callback
        self.title(title)
        self.geometry("500x400")
        self.resizable(False, False)
        # Transient jest OK, ale grab_set() może blokować. Utrzymamy transient.
        # W trybie postępu usuwamy grab.
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.manager = GenerationManager.get_instance()
        self.is_paused = False
        self.is_running = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1) # Main area

        # --- Frames ---
        self.summary_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.summary_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.progress_frame.grid_remove() # Ukryty na start

        # ================= SUMMARY UI =================
        
        # Nagłówek
        ctk.CTkLabel(self.summary_frame, text="Podsumowanie zadania", font=("", 18, "bold")).pack(pady=(10, 10))

        # Statystyki
        to_process = total_count - existing_count
        stats_text = (
            f"Wszystkich elementów: {total_count}\n"
            f"Już istniejących: {existing_count}\n\n"
            f"Domyślnie do wykonania: {to_process}"
        )
        self.lbl_stats = ctk.CTkLabel(self.summary_frame, text=stats_text, justify="center", font=("", 14))
        self.lbl_stats.pack(pady=10)

        # Opcja nadpisywania
        self.var_overwrite = tk.BooleanVar(value=False)
        self.chk_overwrite = ctk.CTkCheckBox(
            self.summary_frame,
            text="Zastąp istniejące (wszystkie od nowa)",
            variable=self.var_overwrite,
            command=self._update_stats_preview
        )
        self.chk_overwrite.pack(pady=15)

        # Przyciski Summary
        btn_frame = ctk.CTkFrame(self.summary_frame, fg_color="transparent")
        btn_frame.pack(pady=20, fill="x", padx=20)

        ctk.CTkButton(btn_frame, text="Anuluj", command=self.destroy, fg_color="gray").pack(side="left", expand=True, padx=5)
        self.btn_confirm = ctk.CTkButton(btn_frame, text="Rozpocznij", command=self._on_confirm, fg_color="#2E8B57", hover_color="#1E613B")
        self.btn_confirm.pack(side="right", expand=True, padx=5)


        # ================= PROGRESS UI =================
        
        ctk.CTkLabel(self.progress_frame, text="Przetwarzanie w toku...", font=("", 18, "bold")).pack(pady=(20, 20))
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, width=400, height=20)
        self.progress_bar.pack(pady=10)
        self.progress_bar.set(0)
        
        self.lbl_progress = ctk.CTkLabel(self.progress_frame, text="Inicjalizacja...", font=("", 12))
        self.lbl_progress.pack(pady=5)
        
        # Controls
        ctrl_frame = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        ctrl_frame.pack(pady=20)
        
        self.btn_pause = ctk.CTkButton(
            ctrl_frame, text="Wstrzymaj", command=self._toggle_pause, 
            fg_color="orange", hover_color="darkorange", width=120
        )
        self.btn_pause.grid(row=0, column=0, padx=10)
        
        self.btn_stop = ctk.CTkButton(
            ctrl_frame, text="Anuluj", command=self._stop_job,
            fg_color="red", hover_color="darkred", width=120
        )
        self.btn_stop.grid(row=0, column=1, padx=10)
        
        self.btn_close_progress = ctk.CTkButton(
            self.progress_frame, text="Zamknij", command=self.destroy,
            fg_color="gray", state="disabled", width=100
        )
        self.btn_close_progress.pack(side="bottom", pady=10)

        # Inicjalny update tekstu przycisku
        self._update_stats_preview()

        # Handle close
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _update_stats_preview(self):
        """Aktualizuje tekst w zależności od checkboxa."""
        pass

    def _on_confirm(self):
        overwrite = self.var_overwrite.get()
        # Wywołujemy callback (który dodaje job do managera)
        success = self.callback(overwrite)
        
        if success:
            self._switch_to_progress_view()
        else:
            # Jeśli false (np. brak modelu), okno zostaje w trybie summary lub user je zamknie
            pass

    def _switch_to_progress_view(self):
        self.summary_frame.grid_remove()
        self.progress_frame.grid()
        self.is_running = True
        self.grab_release() # Odblokuj UI pod spodem
        
        # Rejestracja observerów
        self.manager.register_progress_observer(self._update_progress_safe)
        
    def _update_progress_safe(self, current, total, message):
        if not self.winfo_exists():
            return
            
        # Aktualizacja UI w wątku głównym
        # Używamy after zamiast queue mastera dla prostoty, jeśli master nie ma queue
        # Jeśli caller ma queue, super, ale after(0, ...) działa w ctk.
        self.after(0, lambda: self.update_progress(current, total, message))

    def update_progress(self, current, total, message):
        self.lbl_progress.configure(text=message)
        
        if total > 0:
            val = current / total
            self.progress_bar.set(val)
        elif current == -1:
            self.progress_bar.configure(mode="indeterminate")
            self.progress_bar.start()
        
        if current == total and total > 0:
            self._on_finished()

    def _on_finished(self):
        self.is_running = False
        self.btn_pause.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        self.btn_close_progress.configure(state="normal", fg_color="#2E8B57", hover_color="#1E613B")
        self.lbl_progress.configure(text="Zakończono pomyślnie.")
        self.manager.unregister_progress_observer(self._update_progress_safe)

    def _toggle_pause(self):
        if not self.is_paused:
            self.manager.pause_current_job()
            self.btn_pause.configure(text="Wznów", fg_color="green", hover_color="darkgreen")
            self.is_paused = True
            self.lbl_progress.configure(text="Wstrzymano.")
        else:
            self.manager.resume_current_job()
            self.btn_pause.configure(text="Wstrzymaj", fg_color="orange", hover_color="darkorange")
            self.is_paused = False
            self.lbl_progress.configure(text="Wznawianie...")

    def _stop_job(self):
        self.manager.cancel_current_job()
        self.lbl_progress.configure(text="Anulowanie...")
        self.btn_stop.configure(state="disabled")
        self.btn_pause.configure(state="disabled")
        # Okno zamknie się lub przejdzie w stan closeable po otrzymaniu sygnału progress update

    def on_close(self):
        if self.is_running:
             response = tk.messagebox.askyesno("Zamykanie", "Zadanie w toku. Czy na pewno chcesz przerwać?", parent=self)
             if not response:
                 return
             self._stop_job()
        
        self.manager.unregister_progress_observer(self._update_progress_safe)
        self.destroy()
