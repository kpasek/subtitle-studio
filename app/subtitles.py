import shutil

import customtkinter as ctk
import tkinter as tk
import re
import subprocess
import os
from pathlib import Path
from typing import List, Tuple, Optional
from tkinter import messagebox

from app.editor import LineEditor


FFPLAY_AVAILABLE = shutil.which("ffplay") is not None


class SubtitlePanel(ctk.CTkFrame):
    """
    Panel zarządzający listą napisów, podglądem, odtwarzaniem audio
    oraz edycją linii.
    """

    def __init__(self, master, app, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app
        self.current_audio_process: Optional[subprocess.Popen] = None

        self.grid_rowconfigure(5, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._create_widgets()

    def _create_widgets(self):
        # --- Górny pasek (Zatwierdź zmiany + Widok + Nazwa pliku) ---
        stats_frame = ctk.CTkFrame(self)
        stats_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkButton(stats_frame, text="Zatwierdź zmiany",
                      command=self.app.apply_processing,
                      fg_color="#2E8B57", hover_color="#1E613B").pack(side="left", padx=5)

        ctk.CTkLabel(stats_frame, text="Widok:").pack(side="left", padx=(15, 5))
        self.view_switcher = ctk.CTkSegmentedButton(
            stats_frame,
            values=["Oryginał", "Napisy", "TTS"],
            variable=self.app.view_mode,
            command=self._on_view_mode_change,
            width=200
        )
        self.view_switcher.pack(side="left", padx=5)

        self.app.update_button = ctk.CTkButton(stats_frame, text="Nowa wersja!",
                                               command=self.app._download_update,
                                               fg_color="#006400", hover_color="#004d00")
        self.app.update_button.pack(side="left", padx=5)
        self.app.update_button.pack_forget()

        self.app.lbl_filename = ctk.CTkLabel(stats_frame, text="Brak wczytanego pliku")
        self.app.lbl_filename.pack(side="left", anchor="w", padx=5)

        # --- Audio buttons (Pasek narzędzi) ---
        audio_btn_frame = ctk.CTkFrame(self)
        audio_btn_frame.grid(row=2, column=0, sticky="ew", pady=(0, 5), padx=5)

        self.play_button = ctk.CTkButton(audio_btn_frame, text="▶️ Odtwórz", width=80, command=self.play_selected_audio,
                                         state="disabled")
        self.play_button.pack(side="left", padx=(0, 4))
        if not FFPLAY_AVAILABLE:
            self.play_button.configure(state="disabled", text="N/A ffplay")

        self.audio_select_var = tk.StringVar(value="(brak plików)")
        self.audio_select = ctk.CTkOptionMenu(audio_btn_frame, variable=self.audio_select_var, values=["(brak plików)"])
        self.audio_select.pack(side="left", padx=(4, 8))

        self.generate_button = ctk.CTkButton(audio_btn_frame, text="⚙️ Generuj", width=80,
                                             command=self.app.enqueue_generate_single, state="disabled",
                                             fg_color="#2E8B57", hover_color="#1E613B")
        self.generate_button.pack(side="left", padx=4)

        self.delete_all_button = ctk.CTkButton(audio_btn_frame, text="🗑️ Usuń audio", width=100,
                                               command=self.delete_all_selected_audio, state="disabled",
                                               fg_color="#C51616", hover_color="#920F0F")
        self.delete_all_button.pack(side="left", padx=4)

        # --- Search bar ---
        search_frame = ctk.CTkFrame(self)
        search_frame.grid(row=3, column=0, sticky="ew", pady=(0, 5), padx=5)
        search_frame.grid_columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="Przeszukaj podgląd")
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Return>", lambda event: self.app.apply_patterns())
        self.search_entry.bind("<Control-BackSpace>", lambda event: self.search_entry.delete(0, tk.END))

        self.search_button = ctk.CTkButton(search_frame, text="Szukaj", command=self.app.apply_patterns)
        self.search_button.grid(row=0, column=1, padx=(6, 0))

        # --- Preview Textbox ---
        self.txt_preview = ctk.CTkTextbox(self)
        self.txt_preview.grid(row=5, column=0, sticky="nsew", padx=5, pady=(0, 5))
        self.txt_preview.configure(state=tk.DISABLED)
        self.txt_preview.tag_config("selected_line", background="gray25", foreground="white")
        self.txt_preview.bind("<ButtonRelease-1>", self.on_preview_click)
        self.txt_preview.bind("<Double-Button-1>", self.play_selected_audio)
        self.txt_preview.bind("<Control-Button-1>", self.app.add_replace_pattern_from_selection)
        self.txt_preview.bind("<Delete>", self.app.add_remove_pattern_from_selection)
        self.txt_preview.configure(cursor="hand2")

        # --- Editor ---
        self.editor = LineEditor(self, on_save_callback=self.on_manual_edit_save)
        self.editor.grid(row=6, column=0, sticky="ew", padx=5, pady=(0, 5))

    def _on_view_mode_change(self, value):
        """Obsługa zmiany widoku (Oryginał/Napisy/TTS)."""
        self.app.apply_patterns()
        # Odśwież edytor dla aktualnie zaznaczonej linii (jeśli jest)
        if self.app.selected_line_index is not None:
            self.on_preview_click(None)
        else:
            self.editor.clear()

    def filter_preview(self, lines: List[str]) -> List[str]:
        """Filtruje linie w podglądzie na podstawie wyszukiwania."""
        search_term = self.search_entry.get()
        if not search_term:
            return lines
        try:
            pattern = search_term.lower()
            return [line for line in lines if re.search(pattern, line, re.IGNORECASE)]
        except re.error:
            return lines

    def set_preview(self, lines_to_show: list[str]):
        """Aktualizuje pole tekstowe podglądu."""
        # Reset zaznaczenia w app
        self.app.selected_line_index = None
        self.txt_preview.tag_remove("selected_line", "1.0", tk.END)

        total_lines = len(lines_to_show)
        num_digits = len(str(total_lines)) if total_lines > 0 else 1
        numbered_lines = [
            f"{str(i + 1).zfill(num_digits)} | {line}"
            for i, line in enumerate(lines_to_show)
        ]

        filtered = self.filter_preview(numbered_lines)

        self.txt_preview.configure(state='normal')
        self.txt_preview.delete('1.0', tk.END)
        if filtered:
            self.txt_preview.insert('1.0', '\n'.join(filtered))
        self.txt_preview.configure(state='disabled')

        # Wyczyść edytor po odświeżeniu listy
        self.editor.clear()

    def on_preview_click(self, event):
        """Obsługa kliknięcia w listę napisów."""
        try:
            if event:
                click_index = self.txt_preview.index(f"@{event.x},{event.y}")
            else:
                click_index = self.txt_preview.index(tk.INSERT)

            line_number_str = click_index.split('.')[0]
            visible_line_index = int(line_number_str) - 1

            all_visible_lines = self.txt_preview.get("1.0", tk.END).splitlines()
            if visible_line_index >= len(all_visible_lines):
                return

            clicked_line_content = all_visible_lines[visible_line_index]
            match = re.match(r"^\s*(\d+)\s*\|", clicked_line_content)

            if match:
                original_line_number = int(match.group(1))
                self.app.selected_line_index = original_line_number - 1  # 0-based

                self.txt_preview.tag_remove("selected_line", "1.0", tk.END)
                line_start = f"{line_number_str}.0"
                line_end = f"{line_number_str}.end"
                self.txt_preview.tag_add("selected_line", line_start, line_end)

                # --- Ładowanie tekstu do edytora ---
                mode = self.app.view_mode.get()
                text_to_edit = ""
                read_only = (mode == "Oryginał")

                if not read_only:
                    try:
                        idx = self.app.selected_line_index
                        if mode == "Napisy":
                            # Pobierz z warstwy CLEAN (uwzględnia manual_edits)
                            text_to_edit = self.app.processed_clean[idx]
                        elif mode == "TTS":
                            # Pobierz z warstwy TTS (uwzględnia tts_edits)
                            # tts_edits ma priorytet nad wygenerowanym processed_replace
                            text_to_edit = self.app.processed_replace[idx]
                    except IndexError:
                        pass

                self.editor.set_content(text_to_edit, read_only=read_only)
            else:
                self.app.selected_line_index = None
                self.editor.clear()
                self.txt_preview.tag_remove("selected_line", "1.0", tk.END)

        except (ValueError, tk.TclError, IndexError):
            self.app.selected_line_index = None
            self.editor.clear()
            self.txt_preview.tag_remove("selected_line", "1.0", tk.END)

        self.update_audio_buttons_state()

    def on_manual_edit_save(self, new_text: str):
        """Callback zapisu edycji z LineEditor."""
        if self.app.selected_line_index is None:
            return

        idx = self.app.selected_line_index
        mode = self.app.view_mode.get()

        if mode == "Napisy":
            print(f"Zapisuję edycję (Subtitles) linia {idx + 1}")
            self.app.manual_edits[idx] = new_text
            self.app._save_manual_edits()
        elif mode == "TTS":
            print(f"Zapisuję edycję (TTS) linia {idx + 1}")
            self.app.tts_edits[idx] = new_text
            self.app._save_tts_edits()

        # Odśwież widok
        self.app.apply_patterns()

        # Przywróć stan edytora (aby pokazać, że zapisano)
        self.on_preview_click(None)

    # --- AUDIO METHODS (Moved from Studio) ---

    def _find_audio_files(self, identifier: str) -> List[Tuple[Path, bool]]:
        """Znajduje pliki audio dla danego identyfikatora."""
        if not self.app.audio_dir:
            return []
        candidates = [
            (self.app.audio_dir / f"output1 ({identifier}).wav", False),
            (self.app.audio_dir / f"output1 ({identifier}).mp3", False),
            (self.app.audio_dir / f"output1 ({identifier}).ogg", False),
        ]
        return [(f, ready) for f, ready in candidates if f.exists()]

    def update_audio_buttons_state(self):
        """Aktualizuje stan przycisków audio."""
        line_selected = self.app.selected_line_index is not None
        audio_dir_set = self.app.audio_dir is not None and self.app.audio_dir.is_dir()
        project_loaded = self.app.current_project_path is not None
        lines_processed = bool(self.app.processed_replace)

        files_exist = False
        if line_selected and audio_dir_set:
            identifier = str(self.app.selected_line_index + 1)
            found_files = self._find_audio_files(identifier)
            files_exist = bool(found_files)

            if found_files:
                file_names = [f.name for f, _ in found_files]
                self.audio_select.configure(values=file_names)
                self.audio_select_var.set(file_names[0])
            else:
                self.audio_select.configure(values=["(brak plików)"])
                self.audio_select_var.set("(brak plików)")

        play_state = "normal" if FFPLAY_AVAILABLE and line_selected and audio_dir_set and files_exist else "disabled"
        gen_state = "normal" if line_selected and audio_dir_set and project_loaded and lines_processed else "disabled"
        del_all_state = "normal" if line_selected and audio_dir_set and files_exist else "disabled"

        self.play_button.configure(state=play_state)
        self.generate_button.configure(state=gen_state)
        self.delete_all_button.configure(state=del_all_state)

    def stop_audio(self):
        """Zatrzymuje proces ffplay."""
        if self.current_audio_process:
            try:
                self.current_audio_process.terminate()
                self.current_audio_process = None
            except Exception:
                self.current_audio_process = None

    def play_selected_audio(self, event=None):
        """Odtwarza wybrane audio."""
        if not FFPLAY_AVAILABLE:
            return

        if self.app.selected_line_index is None:
            return
        identifier = str(self.app.selected_line_index + 1)

        if not self.app.audio_dir:
            return

        files = self._find_audio_files(identifier)
        if files:
            selected_name = self.audio_select_var.get()
            file_to_play = next(
                (f for f, _ in files if f.name == selected_name), files[0][0])

            self.stop_audio()

            try:
                print(f"Odtwarzam: {file_to_play}")
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                cmd = ["ffplay", "-nodisp", "-autoexit", str(file_to_play)]

                self.current_audio_process = subprocess.Popen(
                    cmd,
                    startupinfo=startupinfo,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                self.current_audio_process = None
                messagebox.showerror(
                    "Błąd odtwarzania", f"Nie udało się uruchomić ffplay:\n{e}", parent=self)
        else:
            messagebox.showinfo(
                "Brak pliku", "Brak plików audio dla tej linii.", parent=self)

    def delete_all_selected_audio(self):
        """Usuwa wszystkie pliki audio dla wybranej linii."""
        if self.app.selected_line_index is None:
            return
        identifier = str(self.app.selected_line_index + 1)

        if not self.app.audio_dir:
            return

        files = self._find_audio_files(identifier)
        if not files:
            messagebox.showinfo(
                "Brak plików", "Brak plików audio do usunięcia dla tej linii.", parent=self)
            return

        if self.current_audio_process and self.current_audio_process.poll() is None:
            messagebox.showwarning("Plik w użyciu",
                                   "Audio jest odtwarzane. Zatrzymaj je przed usunięciem.",
                                   parent=self)
            return

        file_list_str = "\n".join([f.name for f, rdy in files])
        if not messagebox.askyesno("Potwierdź usunięcie",
                                   f"Czy na pewno usunąć WSZYSTKIE ({len(files)}) pliki dla linii {identifier}?\n{file_list_str}",
                                   parent=self):
            return

        self.stop_audio()

        deleted_count = 0
        errors = []
        for file_path, _ in files:
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception as e:
                errors.append(f"{file_path.name}: {e}")

        if errors:
            messagebox.showerror("Błąd usuwania",
                                 f"Usunięto {deleted_count} z {len(files)} plików.\nBłędy:\n" + "\n".join(
                                     errors),
                                 parent=self)
        else:
            messagebox.showinfo("Usunięto", f"Pomyślnie usunięto {deleted_count} plików dla linii {identifier}.",
                                parent=self)

        self.update_audio_buttons_state()