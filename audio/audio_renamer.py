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
    Okno do przesuwania/dopasowywania plików audio.
    Użytkownik podaje numer linii w tekście i numer pliku audio, który powinien do niej pasować.
    Aplikacja wylicza przesunięcie.
    """

    def __init__(self, parent, audio_dir: Path):
        super().__init__(parent)
        self.parent_app = parent
        self.audio_dir = audio_dir

        self.title("Dopasuj identyfikatory audio")
        self.geometry("550x300")
        self.resizable(False, False)

        self.grab_set()
        self.transient(parent)
        self.grid_columnconfigure(0, weight=1)

        # Informacja
        ctk.CTkLabel(self, text="Dopasowanie numeracji audio", font=("", 14, "bold")).pack(pady=10)
        ctk.CTkLabel(self, text="Przykład: Audio 'output1 (5).wav' ma pasować do Linii nr 10.\n"
                                "Wpisz poniżej: Linia: 10, Audio: 5. (Przesunięcie = +5)",
                     text_color="gray").pack(pady=5)

        # Formularz
        form_frame = ctk.CTkFrame(self)
        form_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(form_frame, text="Docelowy numer linii w napisach:").grid(row=0, column=0, padx=10, pady=5,
                                                                               sticky="e")
        self.ent_target_line = ctk.CTkEntry(form_frame, width=100)
        self.ent_target_line.grid(row=0, column=1, padx=10, pady=5, sticky="w")

        ctk.CTkLabel(form_frame, text="Aktualny numer w nazwie pliku audio:").grid(row=1, column=0, padx=10, pady=5,
                                                                                   sticky="e")
        self.ent_current_file = ctk.CTkEntry(form_frame, width=100)
        self.ent_current_file.grid(row=1, column=1, padx=10, pady=5, sticky="w")

        self.btn_run = ctk.CTkButton(
            self, text="Oblicz i zmień nazwy", command=self.start_rename_task)
        self.btn_run.pack(pady=20, padx=10)

        self.status_label = ctk.CTkLabel(self, text="", text_color="gray")
        self.status_label.pack(fill="x", padx=10, pady=(5, 10))

    def update_status(self, text, color="gray"):
        self.status_label.configure(text=text, text_color=color)

    def set_controls_state(self, state: str):
        self.btn_run.configure(state=state)
        self.ent_target_line.configure(state=state)
        self.ent_current_file.configure(state=state)

    def start_rename_task(self):
        try:
            target_line = int(self.ent_target_line.get())
            current_file_id = int(self.ent_current_file.get())
        except ValueError:
            self.update_status("Błąd: Wprowadzone wartości muszą być liczbami.", color="red")
            return

        offset = target_line - current_file_id

        if offset == 0:
            self.update_status("Błąd: Przesunięcie wynosi 0. Pliki są już zgodne?", color="yellow")
            return

        self.set_controls_state("disabled")
        self.update_status(f"Pracuję... (Przesunięcie: {offset:+d})", color="cyan")

        # Uruchom w wątku
        threading.Thread(
            target=self._rename_files_task,
            args=(current_file_id, offset),
            daemon=True
        ).start()

    def _rename_files_task(self, start_from_id: int, offset: int):
        try:
            search_dirs = [self.audio_dir, self.audio_dir / "ready"]
            file_pattern = re.compile(r"^(output[12])\s*\(\s*(\d+)\s*\)(\.(?:wav|mp3|ogg))$", re.IGNORECASE)

            all_files_info = []

            # 1. Zbierz wszystkie pliki
            for dir_path in search_dirs:
                if not dir_path.is_dir(): continue
                for f in dir_path.iterdir():
                    if f.is_file():
                        match = file_pattern.match(f.name)
                        if match:
                            prefix, id_str, suffix = match.groups()
                            file_id = int(id_str)
                            # Zbieramy tylko te od punktu startowego w górę
                            if file_id >= start_from_id:
                                all_files_info.append((f, prefix, file_id, suffix.lower()))

            if not all_files_info:
                self.parent_app.queue.put(
                    lambda: self.update_status("Nie znaleziono plików do zmiany.", color="yellow"))
                return

            # 2. Sortowanie bezpieczne
            # Jeśli przesuwamy w górę (np. +5), musimy zmieniać od końca (największe ID pierwsze)
            # Jeśli w dół (-5), od początku (najmniejsze ID pierwsze)
            sort_reverse = True if offset > 0 else False
            all_files_info.sort(key=lambda x: x[2], reverse=sort_reverse)

            renamed_count = 0

            for (old_path, prefix, old_id, suffix) in all_files_info:
                new_id = old_id + offset

                if new_id <= 0:
                    print(f"Pominięto {old_path.name}: Nowe ID {new_id} <= 0.")
                    continue

                new_name = f"{prefix} ({new_id}){suffix}"
                new_path = old_path.parent / new_name

                if new_path.exists():
                    # Teoretycznie przy sortowaniu nie powinno wystąpić, chyba że nadpisujemy pliki spoza zakresu edycji
                    # W tym prostym narzędziu lepiej pominąć niż zniszczyć dane
                    print(f"Konflikt: {new_path} już istnieje.")
                    continue

                os.rename(old_path, new_path)
                renamed_count += 1

            msg = f"Zakończono. Zmieniono nazwę: {renamed_count} plików."
            self.parent_app.queue.put(lambda: self.update_status(msg, color="green"))

        except Exception as e:
            self.parent_app.queue.put(lambda: self.update_status(f"Błąd: {str(e)}", color="red"))
        finally:
            self.parent_app.queue.put(lambda: self.set_controls_state("normal"))