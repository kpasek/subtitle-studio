import customtkinter as ctk
import tkinter as tk
from typing import Callable, Optional


class LineEditor(ctk.CTkFrame):
    """
    Komponent do ręcznej edycji pojedynczej linii tekstu.
    Zapisuje zmiany dopiero po wyjściu z pola (FocusOut) lub wciśnięciu Enter.
    """

    def __init__(self, master, on_save_callback: Callable[[str], None], **kwargs):
        super().__init__(master, **kwargs)
        self.on_save_callback = on_save_callback
        self.last_saved_text: Optional[str] = None

        self.grid_columnconfigure(1, weight=1)

        self.label = ctk.CTkLabel(self, text="Edycja linii:")
        self.label.grid(row=0, column=0, padx=5)

        self.entry = ctk.CTkEntry(self, placeholder_text="Wybierz linię aby edytować...")
        self.entry.grid(row=0, column=1, sticky="ew", padx=5, pady=5)

        # Bindings - Zapisz przy utracie fokusu lub Enterze
        self.entry.bind("<FocusOut>", self._on_save)
        self.entry.bind("<Return>", self._on_save)

    def set_content(self, text: str, read_only: bool = False):
        """Ustawia tekst w polu edycji i zarządza jego stanem."""
        self.last_saved_text = text
        self.entry.delete(0, tk.END)
        self.entry.insert(0, text)

        if read_only:
            self.entry.configure(state="disabled", placeholder_text="Edycja niedostępna w trybie oryginału")
        else:
            self.entry.configure(state="normal", placeholder_text="Wybierz linię aby edytować...")

    def clear(self):
        """Czyści pole edycji."""
        self.last_saved_text = None
        self.entry.delete(0, tk.END)
        self.entry.configure(placeholder_text="Wybierz linię aby edytować...")

    def _on_save(self, event=None):
        """Wywołuje callback zapisu, jeśli tekst się zmienił."""
        # Pobieramy aktualny tekst
        current_text = self.entry.get()

        # Sprawdzamy, czy faktycznie coś się zmieniło, aby nie odświeżać bez potrzeby
        # (choć przy FocusOut warto czasem odświeżyć dla pewności)
        if current_text != self.last_saved_text:
            self.last_saved_text = current_text
            self.on_save_callback(current_text)