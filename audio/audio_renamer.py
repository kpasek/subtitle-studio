import os
from pathlib import Path
import re
import threading
from typing import TYPE_CHECKING
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

if TYPE_CHECKING:
    from gui import SubtitleStudioApp


class AudioRenameWindow(ctk.CTkToplevel):
    """
    Okno do masowej zmiany nazw plików audio (przesuwanie ID).
    """

    def __init__(self, parent, audio_dir: Path):
        super().__init__(parent)
        self.parent_app = parent
        self.audio_dir = audio_dir

        self.title("Dopasuj identyfikatory audio")
        self.geometry("450x250")
        self.resizable(False, False)

        self.grab_set()
        self.transient(parent)

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Zmień nazwy plików audio od wiersza (ID):").pack(
            pady=(10, 2), padx=10)
        self.ent_start_id = ctk.CTkEntry(self, placeholder_text="np. 123")
        self.ent_start_id.pack(fill="x", padx=10)

        ctk.CTkLabel(self, text="O wartość (ilość wierszy):").pack(
            pady=(10, 2), padx=10)
        self.ent_shift = ctk.CTkEntry(
            self, placeholder_text="np. 1 (przesunie 123->124) lub -1 (przesunie 123->122)")
        self.ent_shift.pack(fill="x", padx=10)

        self.btn_run = ctk.CTkButton(
            self, text="Wykonaj zmianę nazw", command=self.start_rename_task)
        self.btn_run.pack(pady=20, padx=10)

        self.status_label = ctk.CTkLabel(self, text="", text_color="gray")
        self.status_label.pack(fill="x", padx=10, pady=(5, 10))

    def update_status(self, text, color="gray"):
        self.status_label.configure(text=text, text_color=color)

    def set_controls_state(self, state: str):
        self.btn_run.configure(state=state)
        self.ent_start_id.configure(state=state)
        self.ent_shift.configure(state=state)

    def start_rename_task(self):
        try:
            start_id = int(self.ent_start_id.get())
            shift = int(self.ent_shift.get())
        except ValueError:
            self.update_status(
                "Błąd: Wprowadzone wartości muszą być liczbami.", color="red")
            return

        if shift == 0:
            self.update_status(
                "Błąd: Wartość przesunięcia nie może być 0.", color="red")
            return
        if start_id <= 0:
            self.update_status(
                "Błąd: ID początkowe musi być większe od 0.", color="red")
            return

        self.set_controls_state("disabled")
        self.update_status(f"Pracuję... (Przesunięcie: {shift})", color="cyan")

        # Uruchom w wątku, aby nie blokować GUI
        threading.Thread(
            target=self._rename_files_task,
            args=(start_id, shift),
            daemon=True
        ).start()

    def _rename_files_task(self, start_id: int, shift: int):
        try:
            search_dirs = [self.audio_dir, self.audio_dir / "ready"]
            # Wzór: output1 (123).wav LUB output2 (456).ogg
            file_pattern = re.compile(
                r"^(output[12])\s*\(\s*(\d+)\s*\)(\.(?:wav|mp3|ogg))$", re.IGNORECASE)

            all_files_info = []
            for dir_path in search_dirs:
                if not dir_path.is_dir():
                    continue
                for f in dir_path.iterdir():
                    if f.is_file():
                        match = file_pattern.match(f.name)
                        if match:
                            prefix, id_str, suffix = match.groups()
                            file_id = int(id_str)
                            all_files_info.append(
                                (f, prefix, file_id, suffix.lower()))

            # Filtruj pliki, które należy zmienić (ID >= start_id)
            files_to_rename = [
                f_info for f_info in all_files_info if f_info[2] >= start_id]

            if not files_to_rename:
                self.parent_app.queue.put(
                    lambda: self.update_status("Nie znaleziono plików pasujących do kryteriów.", color="yellow"))
                return

            # KLUCZOWA LOGIKA: Sortuj w zależności od kierunku przesunięcia
            # Jeśli dodajemy (shift > 0), idziemy od końca (reverse=True)
            # Jeśli odejmujemy (shift < 0), idziemy od początku (reverse=False)
            sort_reverse = True if shift > 0 else False
            files_to_rename.sort(key=lambda x: x[2], reverse=sort_reverse)

            renamed_count = 0
            skipped_count = 0

            for (old_path, prefix, old_id, suffix) in files_to_rename:
                new_id = old_id + shift

                if new_id <= 0:
                    print(
                        f"Pominięto {old_path.name}: Nowe ID ({new_id}) jest nieprawidłowe.")
                    skipped_count += 1
                    continue

                new_name = f"{prefix} ({new_id}){suffix}"
                new_path = old_path.parent / new_name

                if new_path.exists():
                    # To nie powinno się zdarzyć przy poprawnym sortowaniu, ale to zabezpieczenie
                    raise IOError(
                        f"Konflikt! Plik {new_path.name} już istnieje. Przerwano.")

                if old_path.exists():  # Sprawdź czy plik źródłowy wciąż istnieje
                    os.rename(old_path, new_path)
                    renamed_count += 1
                else:
                    # To mogłoby się zdarzyć, gdyby plik został już przeniesiony (np. output1 (123).wav i output1 (123).ogg)
                    # Ale nasz wzorzec łapie tylko jeden plik na raz. To jest OK.
                    print(f"Pominięto (źródło nie istnieje): {old_path.name}")

            msg = f"Zakończono. Zmieniono nazwę: {renamed_count} plików. Pominięto: {skipped_count}."
            self.parent_app.queue.put(
                lambda: self.update_status(msg, color="green"))

        except Exception as e:
            error_msg = f"Błąd: {e}"
            print(error_msg)
            self.parent_app.queue.put(
                lambda: self.update_status(error_msg, color="red"))
        finally:
            # Zawsze odblokuj kontrolki
            self.parent_app.queue.put(
                lambda: self.set_controls_state("normal"))
