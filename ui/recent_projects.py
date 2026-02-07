import customtkinter as ctk
import tkinter as tk
from pathlib import Path


class RecentProjectsWindow(ctk.CTkToplevel):
    """
    Okno wyświetlające listę ostatnich projektów.
    Pozwala na otwarcie, usunięcie wpisu lub wyczyszczenie historii.
    """

    def __init__(self, parent, recent_paths: list[str], on_open_callback, on_delete_callback, on_clear_callback):
        super().__init__(parent)
        self.title("Ostatnie projekty")
        self.geometry("600x400")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()
        self.parent = parent

        self.on_open = on_open_callback
        self.on_delete = on_delete_callback
        self.on_clear = on_clear_callback
        self.recent_paths = recent_paths

        # Nagłówek
        ctk.CTkLabel(self, text="Wybierz projekt do otwarcia", font=("", 16, "bold")).pack(pady=10)

        # Lista (Scrollable)
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self._refresh_list()

        # Dolny pasek
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", pady=10, padx=10)

        ctk.CTkButton(btn_frame, text="Zamknij", command=self.destroy, width=100, fg_color="gray").pack(side="right",
                                                                                                        padx=5)
        ctk.CTkButton(btn_frame, text="Wyczyść historię", command=self._clear_all, width=120, fg_color="#C51616",
                      hover_color="#920F0F").pack(side="left", padx=5)

    def _refresh_list(self):
        """Przerysowuje listę projektów."""
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        if not self.recent_paths:
            ctk.CTkLabel(self.scroll_frame, text="Brak ostatnich projektów.").pack(pady=20)
            return

        for path_str in self.recent_paths:
            row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            # Przycisk z nazwą pliku i ścieżką
            path_obj = Path(path_str)
            display_text = f"{path_obj.name}  ({path_str})"

            btn_open = ctk.CTkButton(
                row,
                text=display_text,
                anchor="w",
                fg_color="transparent",
                border_width=1,
                text_color=("black", "white"),
                command=lambda p=path_str: self._open_project(p)
            )
            btn_open.pack(side="left", fill="x", expand=True, padx=(0, 5))

            # Przycisk usuwania (X)
            btn_del = ctk.CTkButton(
                row,
                text="X",
                width=30,
                fg_color="#C51616",
                hover_color="#920F0F",
                command=lambda p=path_str: self._delete_entry(p)
            )
            btn_del.pack(side="right")

    def _open_project(self, path):
        self.on_open(self.parent, path)
        self.destroy()

    def _delete_entry(self, path):
        self.on_delete(path)
        # Callback zaktualizował listę w app, ale musimy odświeżyć ją tutaj lokalnie
        # (Zakładamy, że on_delete modyfikuje listę w studio.py, ale my operujemy na self.recent_paths)
        if path in self.recent_paths:
            self.recent_paths.remove(path)
        self._refresh_list()

    def _clear_all(self):
        self.on_clear()
        self.recent_paths = []
        self._refresh_list()