import customtkinter as ctk
import threading


class GenerationProgressWindow(ctk.CTkToplevel):

    def __init__(self, master, cancel_event: threading.Event):
        super().__init__(master)
        self.title("Generowanie audio")
        self.geometry("400x200")  # Zwiększona wysokość na przycisk

        self.cancel_event = cancel_event
        # ======================

        self.label = ctk.CTkLabel(self, text="Rozpoczynanie...", font=("", 14))
        self.label.pack(pady=(20, 10), padx=20, fill="x")

        self.progress_bar = ctk.CTkProgressBar(self, height=15)
        self.progress_bar.pack(pady=10, padx=20, fill="x")
        self.progress_bar.set(0)

        self.cancel_button = ctk.CTkButton(self, text="Zatrzymaj", command=self.on_cancel, fg_color="red",
                                           hover_color="darkred")
        self.cancel_button.pack(pady=10, padx=20)

        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.transient(master)  # Trzymaj okno na wierzchu
        self.grab_set()  # Ustaw modalność

    def update_progress(self, current: int, total: int, message: str):
        """Aktualizuje pasek postępu dla określonej liczby zadań."""
        if self.progress_bar.cget("mode") == "indeterminate":
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")

        progress_val = current / total if total > 0 else 0
        self.progress_bar.set(progress_val)

        percent = int(progress_val * 100)
        self.label.configure(text=f"{message}\n{current} / {total} ({percent}%)")
        self.update_idletasks()

    def set_indeterminate(self, message: str):
        """Ustawia pasek w tryb nieokreślony (np. na czas konwersji)."""
        self.label.configure(text=message)
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.update_idletasks()

    def on_cancel(self):
        """Ustawia flagę anulowania i blokuje przycisk."""
        self.label.configure(text="Zatrzymywanie...")
        self.cancel_button.configure(state="disabled", text="Zatrzymywanie...")
        self.update_idletasks()
        self.cancel_event.set()
        # Okno zostanie zamknięte przez wątek roboczy po zakończeniu