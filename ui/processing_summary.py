import customtkinter as ctk
import tkinter as tk

class ProcessingSummaryWindow(ctk.CTkToplevel):
    """Okno podsumowania i wyboru opcji przed zatwierdzeniem zmian."""
    def __init__(self, master, lines_count, changes_count, manual_edits_count, callback):
        super().__init__(master)
        self.callback = callback
        self.title("Podsumowanie zmian")
        self.geometry("400x350")
        
        self.grid_columnconfigure(0, weight=1)

        # Tytuł
        ctk.CTkLabel(self, text="Podsumowanie przetwarzania", font=("", 18, "bold")).pack(pady=(15, 10))

        # Statystyki
        stats_text = (
            f"Liczba wszystkich linii: {lines_count}\n"
            f"Linii zmienionych przez wzorce: {changes_count}\n"
            f"Ręcznie edytowane linie: {manual_edits_count}"
        )
        ctk.CTkLabel(self, text=stats_text, justify="center").pack(pady=10)

        # Opcje
        self.var_remove_empty = tk.BooleanVar(value=True)
        self.var_remove_duplicates = tk.BooleanVar(value=True)

        ctk.CTkCheckBox(self, text="Usuń puste wiersze", variable=self.var_remove_empty).pack(pady=5, anchor="center")
        ctk.CTkCheckBox(self, text="Usuń duplikaty", variable=self.var_remove_duplicates).pack(pady=5, anchor="center")

        # Przyciski
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=20, fill="x", padx=20)

        ctk.CTkButton(btn_frame, text="Anuluj", command=self.destroy, fg_color="gray").pack(side="left", expand=True, padx=5)
        ctk.CTkButton(btn_frame, text="Zatwierdź", command=self.on_confirm).pack(side="right", expand=True, padx=5)

        self.transient(master)
        self.wait_visibility()
        self.grab_set() 
        self.lift()
        self.focus_force()

    def on_confirm(self):
        """Przekazuje wybrane opcje z powrotem do aplikacji."""
        remove_empty = self.var_remove_empty.get()
        remove_duplicates = self.var_remove_duplicates.get()
        self.callback(remove_empty, remove_duplicates)
        self.destroy()