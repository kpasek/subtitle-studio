import os
from pathlib import Path
import re
import threading
import shutil
import subprocess
from typing import TYPE_CHECKING, Optional, List, Tuple
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

if TYPE_CHECKING:
    from studio import SubtitleStudioApp


class AudioRenameWindow(ctk.CTkToplevel):
    """
    Okno do masowej zmiany nazw plików audio w celu synchronizacji z tekstem.
    Pozwala wskazać linię tekstu i odpowiadający jej (błędny) plik audio.
    """

    def __init__(self, parent: 'SubtitleStudioApp', audio_dir: Path):
        super().__init__(parent)
        self.parent_app = parent
        self.audio_dir = audio_dir
        self.current_audio_process: Optional[subprocess.Popen] = None
        self.ffplay_available = shutil.which("ffplay") is not None

        self.title("Synchronizuj Audio z Tekstem")
        self.geometry("600x450")
        self.resizable(False, False)

        self.grab_set()
        self.transient(parent)

        self.grid_columnconfigure(0, weight=1)

        # --- Sekcja 1: Linia Tekstu (Docelowe ID) ---
        target_frame = ctk.CTkFrame(self)
        target_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(target_frame, text="1. Docelowa linia tekstu (Jakie to powinno mieć ID?)",
                     font=("", 13, "bold")).pack(anchor="w", padx=10, pady=(5, 0))

        tf_inner = ctk.CTkFrame(target_frame, fg_color="transparent")
        tf_inner.pack(fill="x", padx=5, pady=5)

        self.ent_text_id = ctk.CTkEntry(tf_inner, placeholder_text="Nr linii", width=100)
        self.ent_text_id.pack(side="left", padx=5)
        self.ent_text_id.bind("<KeyRelease>", self.on_input_change)

        self.btn_play_target = ctk.CTkButton(tf_inner, text="▶ Odsłuchaj plik pod tym ID", width=180,
                                             command=lambda: self.play_audio_by_id(self.ent_text_id.get()),
                                             fg_color="gray", state="disabled")
        self.btn_play_target.pack(side="left", padx=5)

        self.lbl_text_preview = ctk.CTkLabel(target_frame, text="Treść: ---", text_color="silver", anchor="w",
                                             justify="left")
        self.lbl_text_preview.pack(fill="x", padx=10, pady=(0, 10))

        # --- Sekcja 2: Plik Audio (Źródłowe ID) ---
        source_frame = ctk.CTkFrame(self)
        source_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(source_frame, text="2. Rzeczywisty plik audio (Gdzie ten dźwięk jest teraz?)",
                     font=("", 13, "bold")).pack(anchor="w", padx=10, pady=(5, 0))

        sf_inner = ctk.CTkFrame(source_frame, fg_color="transparent")
        sf_inner.pack(fill="x", padx=5, pady=5)

        self.ent_audio_id = ctk.CTkEntry(sf_inner, placeholder_text="Nr pliku audio", width=100)
        self.ent_audio_id.pack(side="left", padx=5)
        self.ent_audio_id.bind("<KeyRelease>", self.on_input_change)

        self.btn_play_source = ctk.CTkButton(sf_inner, text="▶ Odsłuchaj ten plik", width=180,
                                             command=lambda: self.play_audio_by_id(self.ent_audio_id.get()))
        self.btn_play_source.pack(side="left", padx=5)

        # --- Sekcja 3: Podsumowanie i Akcja ---
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.lbl_summary = ctk.CTkLabel(action_frame, text="Wprowadź numery, aby obliczyć przesunięcie.", font=("", 14))
        self.lbl_summary.pack(pady=10)

        self.btn_run = ctk.CTkButton(
            action_frame, text="Wykonaj zmianę nazw", command=self.start_rename_task,
            height=40, font=("", 14, "bold"), fg_color="green", hover_color="darkgreen", state="disabled")
        self.btn_run.pack(pady=10, fill="x")

        self.status_label = ctk.CTkLabel(self, text="", text_color="gray")
        self.status_label.pack(fill="x", padx=10, pady=(0, 10))

        if not self.ffplay_available:
            self.update_status("Ostrzeżenie: Brak 'ffplay'. Odsłuch niedostępny.", "orange")

    def on_input_change(self, event=None):
        """Aktualizuje podgląd tekstu i obliczenia przesunięcia."""
        text_id_str = self.ent_text_id.get().strip()
        audio_id_str = self.ent_audio_id.get().strip()

        # 1. Podgląd tekstu
        if text_id_str.isdigit():
            idx = int(text_id_str) - 1
            content = self._get_line_content(idx)
            if content:
                # Skróć tekst jeśli za długi
                preview = (content[:70] + '...') if len(content) > 70 else content
                self.lbl_text_preview.configure(text=f"Treść: {preview}")
                self.btn_play_target.configure(state="normal", fg_color="#3B8ED0")  # Standard blue
            else:
                self.lbl_text_preview.configure(text="Treść: <Brak linii o tym numerze>")
                self.btn_play_target.configure(state="disabled", fg_color="gray")
        else:
            self.lbl_text_preview.configure(text="Treść: ---")
            self.btn_play_target.configure(state="disabled", fg_color="gray")

        # 2. Obliczenia
        if text_id_str.isdigit() and audio_id_str.isdigit():
            t_id = int(text_id_str)
            a_id = int(audio_id_str)
            shift = t_id - a_id

            if shift == 0:
                self.lbl_summary.configure(text="Brak przesunięcia (ID są takie same).", text_color="yellow")
                self.btn_run.configure(state="disabled")
            else:
                direction = "do przodu (+)" if shift > 0 else "do tyłu (-)"
                self.lbl_summary.configure(
                    text=f"Akcja: Plik {a_id} stanie się {t_id}.\nPrzesunięcie wszystkich plików od ID {a_id} o {shift} ({direction}).",
                    text_color="white"
                )
                self.btn_run.configure(state="normal")
        else:
            self.lbl_summary.configure(text="Oczekiwanie na poprawne numery...", text_color="gray")
            self.btn_run.configure(state="disabled")

    def _get_line_content(self, index: int) -> Optional[str]:
        """Pobiera tekst z aplikacji (preferuje przetworzony TTS, potem napisy, potem oryginał)."""
        if index < 0: return None

        # Próbujemy pobrać z processed_replace (TTS)
        if self.parent_app.processed_replace and index < len(self.parent_app.processed_replace):
            return self.parent_app.processed_replace[index]

        # Jeśli nie ma, to z processed_clean
        if self.parent_app.processed_clean and index < len(self.parent_app.processed_clean):
            return self.parent_app.processed_clean[index]

        # Ostatecznie oryginał
        if self.parent_app.original_lines and index < len(self.parent_app.original_lines):
            return self.parent_app.original_lines[index]

        return None

    def _find_audio_file(self, identifier: str) -> Optional[Path]:
        """Szuka pliku audio dla danego ID."""
        if not self.audio_dir: return None
        candidates = [
            self.audio_dir / f"output1 ({identifier}).wav",
            self.audio_dir / f"output1 ({identifier}).mp3",
            self.audio_dir / f"output1 ({identifier}).ogg",
            # Sprawdzamy też w ready
            self.audio_dir / "ready" / f"output1 ({identifier}).ogg"
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def stop_audio(self):
        if self.current_audio_process:
            try:
                self.current_audio_process.terminate()
            except Exception:
                pass
            self.current_audio_process = None

    def play_audio_by_id(self, id_str: str):
        if not self.ffplay_available:
            messagebox.showwarning("Brak ffplay", "Program ffplay nie został znaleziony.", parent=self)
            return

        if not id_str.isdigit():
            return

        file_path = self._find_audio_file(id_str)

        self.stop_audio()

        if file_path:
            try:
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                cmd = ["ffplay", "-nodisp", "-autoexit", str(file_path)]
                self.current_audio_process = subprocess.Popen(
                    cmd,
                    startupinfo=startupinfo,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.update_status(f"Odtwarzanie: {file_path.name}", "cyan")
            except Exception as e:
                self.update_status(f"Błąd odtwarzania: {e}", "red")
        else:
            self.update_status(f"Nie znaleziono pliku audio dla ID {id_str}", "orange")

    def update_status(self, text, color="gray"):
        self.status_label.configure(text=text, text_color=color)

    def set_controls_state(self, state: str):
        self.btn_run.configure(state=state)
        self.ent_text_id.configure(state=state)
        self.ent_audio_id.configure(state=state)
        self.btn_play_source.configure(state=state)
        self.btn_play_target.configure(state=state)

    def start_rename_task(self):
        try:
            target_id = int(self.ent_text_id.get())
            source_id = int(self.ent_audio_id.get())
        except ValueError:
            return

        shift = target_id - source_id
        start_id = source_id

        if shift == 0:
            return
        if start_id <= 0:
            self.update_status("Błąd: ID początkowe musi być większe od 0.", color="red")
            return

        self.set_controls_state("disabled")
        self.stop_audio()
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
                    # W przypadku masowego przesuwania (np. insert), plik docelowy może istnieć (to ten, który zaraz przesuniemy),
                    # ale przy sortowaniu od tyłu, on już powinien być przesunięty.
                    # Jeśli jednak istnieje, to znaczy że nadpisujemy coś spoza zakresu naszej operacji, lub operacja jest niebezpieczna.
                    # Dla bezpieczeństwa przerywamy lub oznaczamy błąd.
                    print(f"Konflikt! Plik {new_path.name} już istnieje. Pomijam.")
                    skipped_count += 1
                    continue

                if old_path.exists():  # Sprawdź czy plik źródłowy wciąż istnieje
                    os.rename(old_path, new_path)
                    renamed_count += 1
                else:
                    print(f"Pominięto (źródło nie istnieje): {old_path.name}")

            msg = f"Zakończono. Zmieniono nazwę: {renamed_count} plików. Pominięto: {skipped_count}."
            self.parent_app.queue.put(
                lambda: self.update_status(msg, color="green"))

            # Odśwież UI w oknie głównym
            self.parent_app.queue.put(self.parent_app.subtitle_panel.update_audio_buttons_state)

        except Exception as e:
            error_msg = f"Błąd: {e}"
            print(error_msg)
            self.parent_app.queue.put(
                lambda: self.update_status(error_msg, color="red"))
        finally:
            # Zawsze odblokuj kontrolki
            self.parent_app.queue.put(
                lambda: self.set_controls_state("normal"))
            # Wyczyść pola po sukcesie? Może lepiej nie, żeby widzieć co się stało.