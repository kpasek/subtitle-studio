import customtkinter as ctk
import tkinter as tk
from typing import Callable, Optional


class LineEditor(ctk.CTkFrame):
    """
    Komponent do ręcznej edycji pojedynczej linii tekstu.
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

        self.entry.bind("<FocusOut>", self._on_save)
        self.entry.bind("<Return>", self._on_save)


    def clear(self):
        """Czyści pole edycji i przywraca domyślny placeholder."""
        self.last_saved_text = None
        self.entry.delete(0, tk.END)
        self.entry.configure(placeholder_text="Wybierz linię aby edytować...")

    def _on_save(self, event=None):
        current_text = self.entry.get()
        if current_text != self.last_saved_text:
            self.last_saved_text = current_text
            self.on_save_callback(current_text)