import customtkinter as ctk
import tkinter as tk


class GenerationSummaryWindow(ctk.CTkToplevel):
    """
    Okno dialogowe wyświetlające podsumowanie przed generowaniem lub konwersją.
    Pozwala użytkownikowi zdecydować, czy nadpisać istniejące pliki.
    """

    def __init__(self, parent, title, total_count, existing_count, callback):
        super().__init__(parent)
        self.callback = callback
        self.title(title)
        self.geometry("400x300")
        self.resizable(False, False)
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)

        # Nagłówek
        ctk.CTkLabel(self, text="Podsumowanie zadania", font=("", 18, "bold")).pack(pady=(20, 10))

        # Statystyki
        to_process = total_count - existing_count
        stats_text = (
            f"Wszystkich elementów: {total_count}\n"
            f"Już istniejących: {existing_count}\n\n"
            f"Domyślnie do wykonania: {to_process}"
        )
        self.lbl_stats = ctk.CTkLabel(self, text=stats_text, justify="center", font=("", 14))
        self.lbl_stats.pack(pady=10)

        # Opcja nadpisywania
        self.var_overwrite = tk.BooleanVar(value=False)
        self.chk_overwrite = ctk.CTkCheckBox(
            self,
            text="Zastąp istniejące (wszystkie od nowa)",
            variable=self.var_overwrite,
            command=self._update_stats_preview
        )
        self.chk_overwrite.pack(pady=15)

        # Przyciski
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=20, fill="x", padx=20)

        ctk.CTkButton(btn_frame, text="Anuluj", command=self.destroy, fg_color="gray").pack(side="left", expand=True,
                                                                                            padx=5)
        self.btn_confirm = ctk.CTkButton(btn_frame, text="Rozpocznij", command=self._on_confirm, fg_color="#2E8B57",
                                         hover_color="#1E613B")
        self.btn_confirm.pack(side="right", expand=True, padx=5)

        # Inicjalny update tekstu przycisku
        self._update_stats_preview()

    def _update_stats_preview(self):
        """Aktualizuje tekst w zależności od checkboxa."""
        # Logika tylko wizualna, właściwa logika jest w callbacku
        pass

    def _on_confirm(self):
        overwrite = self.var_overwrite.get()
        self.callback(overwrite)
        self.destroy()