import shutil
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import subprocess
import os
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
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
        self._search_job = None

        # Konfiguracja kolumn - tutaj można łatwo dodawać nowe kolumny w przyszłości
        self.columns_config = [
            {"id": "line_nr", "text": "Nr", "width": 25, "anchor": "center"},
            {"id": "content", "text": "Tekst", "width": 600, "anchor": "w"},
        ]

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._create_widgets()

    def _create_widgets(self):
        # --- Górny pasek stats_frame - Row 0 ---
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

        # --- Audio/Action buttons + Pasek Wyszukiwania - Row 1 ---
        audio_btn_frame = ctk.CTkFrame(self)
        audio_btn_frame.grid(row=1, column=0, sticky="ew", pady=(0, 5), padx=5)

        audio_btn_frame.grid_columnconfigure(5, weight=1)

        self.play_button = ctk.CTkButton(audio_btn_frame, text="▶️ Odtwórz", width=120,
                                         command=self.play_selected_audio,
                                         state="disabled")
        self.play_button.grid(row=0, column=0, padx=(0, 4))
        if not FFPLAY_AVAILABLE:
            self.play_button.configure(state="disabled", text="N/A ffplay")

        self.generate_button = ctk.CTkButton(audio_btn_frame, text="⚙️ Generuj", width=80,
                                             command=self.app.enqueue_generate_single, state="disabled",
                                             fg_color="#2E8B57", hover_color="#1E613B")
        self.generate_button.grid(row=0, column=1, padx=4)

        self.delete_all_button = ctk.CTkButton(audio_btn_frame, text="🗑️ Usuń audio", width=100,
                                               command=self.delete_all_selected_audio, state="disabled",
                                               fg_color="#C51616", hover_color="#920F0F")
        self.delete_all_button.grid(row=0, column=2, padx=4)

        # --- Pasek Wyszukiwania ---
        ctk.CTkLabel(audio_btn_frame, text="Szukaj").grid(row=0, column=3, padx=(15, 5))

        self.search_line_nr = ctk.CTkEntry(audio_btn_frame, placeholder_text="Nr linii", width=80)
        self.search_line_nr.grid(row=0, column=4, padx=(0, 5))

        self.search_line_nr.bind("<KeyRelease>", self._schedule_jump_to_line)
        self.search_line_nr.bind("<Return>", self._jump_to_line)

        # Pole do wyszukiwania tekstu
        self.search_entry = ctk.CTkEntry(audio_btn_frame, placeholder_text="Tekst")
        self.search_entry.grid(row=0, column=5, sticky="ew")
        self.search_entry.bind("<Return>", lambda event: self.app.apply_patterns())
        self.search_entry.bind("<Control-BackSpace>", lambda event: self.search_entry.delete(0, tk.END))

        self.search_button = ctk.CTkButton(audio_btn_frame, text="Szukaj", command=self.app.apply_patterns, width=60)
        self.search_button.grid(row=0, column=6, padx=(6, 0))

        # --- Preview Table (Lista napisów jako Tabela) - Row 2 ---
        # Kontener dla tabeli i paska przewijania
        table_frame = ctk.CTkFrame(self, fg_color="transparent")
        table_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=(0, 5))
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # Stylizacja Treeview (aby pasowało do ciemnego motywu CustomTkinter)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background="#2b2b2b",
                        foreground="white",
                        fieldbackground="#2b2b2b",
                        bordercolor="#2b2b2b",
                        lightcolor="#2b2b2b",
                        darkcolor="#2b2b2b",
                        rowheight=25)
        style.configure("Treeview.Heading",
                        background="#1c1c1c",
                        foreground="white",
                        relief="flat")
        style.map("Treeview.Heading",
                  background=[('active', '#252525')])
        style.map("Treeview",
                  background=[('selected', '#1f538d')],
                  foreground=[('selected', 'white')])

        # Pobieramy ID kolumn z konfiguracji
        column_ids = [col["id"] for col in self.columns_config]

        self.tree = ttk.Treeview(table_frame, columns=column_ids, show="headings", selectmode="browse")

        # Konfiguracja nagłówków i kolumn na podstawie self.columns_config
        for col_conf in self.columns_config:
            self.tree.heading(col_conf["id"], text=col_conf["text"])
            self.tree.column(col_conf["id"], width=col_conf["width"], anchor=col_conf["anchor"])

        self.tree.grid(row=0, column=0, sticky="nsew")

        # Scrollbar
        self.scrollbar = ctk.CTkScrollbar(table_frame, orientation="vertical", command=self.tree.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=self.scrollbar.set)

        # Eventy
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-Button-1>", self.play_selected_audio)
        self.tree.bind("<Button-3>", self._show_context_menu)
        # Obsługa Ctrl+Klik (dodawanie wzorca)
        self.tree.bind("<Control-Button-1>", self.app.add_replace_pattern_from_selection)

        # --- Editor (Edytor Linii) - Row 3 ---
        self.editor = LineEditor(self, on_save_callback=self.on_manual_edit_save)
        self.editor.grid(row=3, column=0, sticky="ew", padx=5, pady=(0, 5))

    def _on_view_mode_change(self, value):
        self.app.apply_patterns()
        if self.app.selected_line_index is not None:
            self._reload_editor_for_selected()
        else:
            self.editor.clear()
        self.app.save_app_setting('last_view_mode', value)

    def _schedule_jump_to_line(self, event=None):
        """Opóźnia wywołanie skoku do linii (debounce), aby uniknąć migania."""
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(200, self._jump_to_line)

    def _jump_to_line(self, event=None):
        """Przewija widok do wpisanego numeru linii i zaznacza ją w tabeli."""
        val = self.search_line_nr.get().strip()
        if not val.isdigit():
            return

        target_nr = int(val)

        # Przeszukujemy elementy drzewa, aby znaleźć odpowiednią linię
        found_item = None
        for item_id in self.tree.get_children():
            item_vals = self.tree.item(item_id, "values")
            # Zakładamy, że kolumna z numerem linii jest pierwsza ("line_nr")
            # item_vals[0] zawiera numer linii jako string
            try:
                if int(item_vals[0]) == target_nr:
                    found_item = item_id
                    break
            except (ValueError, IndexError):
                continue

        if found_item:
            self.tree.selection_set(found_item)
            self.tree.see(found_item)
            self.tree.focus(found_item)  # Ustaw focus, aby klawiatura działała od razu tutaj

            # Stan zaktualizuje się automatycznie przez callback on_tree_select
        else:
            # Nie znaleziono
            pass

    def _reload_editor_for_selected(self):
        if self.app.selected_line_index is None:
            self.editor.clear()
            return

        mode = self.app.view_mode.get()
        text_to_edit = ""
        read_only = (mode == "Oryginał")

        if not read_only:
            try:
                idx = self.app.selected_line_index
                if mode == "Napisy":
                    text_to_edit = self.app.processed_clean[idx]
                elif mode == "TTS":
                    text_to_edit = self.app.processed_replace[idx]
            except IndexError:
                pass

        self.editor.set_content(text_to_edit, read_only=read_only)
        self.update_audio_buttons_state()

    def set_preview(self, lines_to_show: list[str]):
        """
        Wypełnia tabelę danymi.
        Argument lines_to_show to lista tekstów. Numer linii jest wyliczany z indeksu.
        """
        preserved_index = self.app.selected_line_index

        # Wyczyść tabelę
        for item in self.tree.get_children():
            self.tree.delete(item)

        search_term = self.search_entry.get().lower()

        # Przygotuj dane do wstawienia
        # Jeśli w przyszłości lines_to_show będzie listą słowników/obiektów,
        # tutaj trzeba będzie dostosować mapowanie na kolumny.

        item_to_select = None

        for i, line_text in enumerate(lines_to_show):
            # Filtrowanie tekstu (szukajka)
            if search_term and search_term not in line_text.lower():
                continue

            line_nr = i + 1

            # Budowanie wartości dla wiersza zgodnie z self.columns_config
            row_values = []
            for col in self.columns_config:
                col_id = col["id"]
                if col_id == "line_nr":
                    # Formatowanie numeru linii (padding zerami np. 001)
                    # Opcjonalnie można to zrobić dynamicznie na podstawie len(lines_to_show)
                    row_values.append(f"{line_nr:03d}")
                elif col_id == "content":
                    row_values.append(line_text)
                else:
                    # Placeholder dla przyszłych kolumn
                    row_values.append("")

            # Wstawienie wiersza
            item_id = self.tree.insert("", "end", values=tuple(row_values))

            # Sprawdzenie czy ten wiersz ma być zaznaczony (przy odświeżaniu widoku)
            if preserved_index is not None and line_nr == preserved_index + 1:
                item_to_select = item_id

        # Przywrócenie zaznaczenia
        if item_to_select:
            self.tree.selection_set(item_to_select)
            self.tree.see(item_to_select)
        else:
            self.editor.clear()
            self.app.selected_line_index = None
            self.update_audio_buttons_state()

    def on_tree_select(self, event):
        """Obsługa wyboru wiersza w tabeli."""
        selected_items = self.tree.selection()
        if not selected_items:
            self.app.selected_line_index = None
            self.editor.clear()
            self.update_audio_buttons_state()
            return

        # Pobierz pierwszy zaznaczony element
        item_id = selected_items[0]
        item_values = self.tree.item(item_id, "values")

        try:
            # Pobieramy numer linii z pierwszej kolumny (zakładamy że tam jest 'line_nr')
            # Jeśli kolejność kolumn się zmieni, trzeba to zaktualizować lub szukać po indeksie w columns_config
            line_nr_str = item_values[0]
            line_nr = int(line_nr_str)

            self.app.selected_line_index = line_nr - 1
            self._reload_editor_for_selected()
        except (ValueError, IndexError):
            self.app.selected_line_index = None
            self.editor.clear()

        self.update_audio_buttons_state()

    def on_manual_edit_save(self, new_text: str):
        if self.app.selected_line_index is None:
            return

        idx = self.app.selected_line_index
        mode = self.app.view_mode.get()

        if mode == "Napisy":
            self.app.manual_edits[idx] = new_text
            self.app._save_manual_edits()
        elif mode == "TTS":
            self.app.tts_edits[idx] = new_text
            self.app._save_tts_edits()

        self.app.apply_patterns()
        if self.app.selected_line_index is not None:
            self._reload_editor_for_selected()

    def _show_context_menu(self, event):
        # W Treeview zaznaczenie pod prawym przyciskiem myszy nie dzieje się automatycznie w każdym OS
        # Wymuszamy zaznaczenie wiersza pod kursorem
        item_id = self.tree.identify_row(event.y)
        if item_id:
            self.tree.selection_set(item_id)

        # Pobieramy aktualne zaznaczenie (powinno być ustawione wyżej lub wcześniej)
        if not self.tree.selection():
            return

        if self.app.selected_line_index is None:
            return

        menu = tk.Menu(self, tearoff=0)

        can_play = self.play_button.cget("state") == "normal"
        can_gen = self.generate_button.cget("state") == "normal"
        can_del = self.delete_all_button.cget("state") == "normal"
        can_edit = self.editor.entry.cget("state") == "normal"

        menu.add_command(label="▶️ Odtwórz audio (Ctrl+Spacja)", command=self.play_selected_audio,
                         state=tk.NORMAL if can_play else tk.DISABLED)
        menu.add_command(label="⚙️ Generuj audio (Ctrl+G)", command=self.app.enqueue_generate_single,
                         state=tk.NORMAL if can_gen else tk.DISABLED)
        menu.add_command(label="🗑️ Usuń audio (Ctrl+X)", command=self.delete_all_selected_audio,
                         state=tk.NORMAL if can_del else tk.DISABLED)
        menu.add_separator()
        menu.add_command(label="📄 Kopiuj linię (Ctrl+C)", command=lambda: self.app._on_ctrl_c_from_menu(),
                         state=tk.NORMAL)
        menu.add_command(label="❌ Wyczyść treść linii (Del)", command=lambda: self.app._clear_selected_line_content(),
                         state=tk.NORMAL if can_edit else tk.DISABLED)
        menu.add_separator()
        menu.add_command(label="➕ Dodaj wzorzec zamieniający (Ctrl+Klik)",
                         command=lambda: self.app.add_replace_pattern_from_selection(from_menu=True), state=tk.NORMAL)

        # Obliczamy ID. current_line_index jest liczony od 0, a pliki od 1.
        current_id = self.app.selected_line_index + 1

        prev_id = current_id - 1
        if prev_id < 1: prev_id = 1  # Zabezpieczenie, żeby nie poszło na 0

        menu.add_command(
            label=f"Dopasuj audio",
            command=lambda: self.app.open_audio_rename_window(target_id=current_id, source_id=prev_id)
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _find_audio_files(self, identifier: str) -> List[Tuple[Path, bool]]:
        if not self.app.audio_dir:
            return []
        candidates = [
            (self.app.audio_dir / f"output1 ({identifier}).wav", False),
            (self.app.audio_dir / f"output1 ({identifier}).mp3", False),
            (self.app.audio_dir / f"output1 ({identifier}).ogg", False),
        ]
        return [(f, ready) for f, ready in candidates if f.exists()]

    def update_audio_buttons_state(self):
        """
        ZMIANA: Sprawdza obecny stan przycisków przed wykonaniem 'configure',
        aby uniknąć migotania interfejsu.
        """
        line_selected = self.app.selected_line_index is not None
        audio_dir_set = self.app.audio_dir is not None and self.app.audio_dir.is_dir()
        project_loaded = self.app.current_project_path is not None
        lines_processed = bool(self.app.processed_replace)

        files_exist = False
        status_msg = "Audio: ---"

        if line_selected and audio_dir_set:
            identifier = str(self.app.selected_line_index + 1)
            found_files = self._find_audio_files(identifier)
            files_exist = bool(found_files)

            if found_files:
                status_msg = f"Audio: znaleziono {len(found_files)}"
                self.first_found_audio = found_files[0][0]
            else:
                status_msg = "Audio: brak"
                self.first_found_audio = None

        # Aktualizacja statusu (tylko jeśli tekst się zmienił)
        if hasattr(self.app, 'set_audio_status'):
            # (Tu można by dodać sprawdzenie starej wartości, ale ctkLabel zwykle radzi sobie dobrze)
            self.app.set_audio_status(status_msg)

        play_state = "normal" if FFPLAY_AVAILABLE and line_selected and audio_dir_set and files_exist else "disabled"
        gen_state = "normal" if line_selected and audio_dir_set and project_loaded and lines_processed else "disabled"
        del_all_state = "normal" if line_selected and audio_dir_set and files_exist else "disabled"

        # ZMIANA: Sprawdź stan przed aktualizacją
        if self.play_button.cget("state") != play_state:
            self.play_button.configure(state=play_state)

        if self.generate_button.cget("state") != gen_state:
            self.generate_button.configure(state=gen_state)

        if self.delete_all_button.cget("state") != del_all_state:
            self.delete_all_button.configure(state=del_all_state)

    def stop_audio(self):
        if self.current_audio_process:
            try:
                self.current_audio_process.terminate()
                self.current_audio_process = None
            except Exception:
                self.current_audio_process = None

    def play_selected_audio(self, event=None):
        if not FFPLAY_AVAILABLE or self.app.selected_line_index is None or not self.app.audio_dir:
            return

        identifier = str(self.app.selected_line_index + 1)
        files = self._find_audio_files(identifier)
        if files:
            file_to_play = files[0][0]
            self.stop_audio()
            try:
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
                messagebox.showerror("Błąd", f"Nie udało się uruchomić ffplay:\n{e}", parent=self)
        else:
            pass

    def delete_all_selected_audio(self):
        if self.app.selected_line_index is None or not self.app.audio_dir:
            return
        identifier = str(self.app.selected_line_index + 1)
        files = self._find_audio_files(identifier)
        if not files:
            return

        if self.current_audio_process and self.current_audio_process.poll() is None:
            messagebox.showwarning("Plik w użyciu", "Audio jest odtwarzane. Zatrzymaj je przed usunięciem.",
                                   parent=self)
            return

        if not messagebox.askyesno("Potwierdź",
                                   f"Czy na pewno usunąć WSZYSTKIE ({len(files)}) pliki dla linii {identifier}?",
                                   parent=self):
            return

        self.stop_audio()
        for file_path, _ in files:
            try:
                os.remove(file_path)
            except Exception:
                pass
        self.update_audio_buttons_state()