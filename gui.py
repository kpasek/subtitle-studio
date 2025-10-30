from __future__ import annotations

import multiprocessing
import os.path
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import re
import csv
import json
import sys
import os
import shutil
from typing import List, Optional, Tuple
from pathlib import Path
import threading
import queue
import webbrowser

try:
    from packaging import version
    PACKAGING_AVAILABLE = True
except ImportError:
    PACKAGING_AVAILABLE = False
    print("Ostrzeżenie: Biblioteka 'packaging' nie jest zainstalowana. Sprawdzanie aktualizacji będzie wyłączone.")
    print("Aby włączyć, zainstaluj: pip install packaging")

import requests
from customtkinter import CTkFrame, CTkScrollableFrame

from app.settings import SettingsWindow
from app.utils import apply_remove_patterns, apply_replace_patterns, resource_path, is_installed
from app.entity import PatternItem
from app.tooltip import CreateToolTip

from audio.audio_renamer import AudioRenameWindow
from audio.pattern_editor import PatternEditorWindow
from audio.progress import GenerationProgressWindow
from audio.deleter import AudioDeleterWindow
from audio.progress import GenerationProgressWindow
from audio.generation_manager import GenerationManager, GenerationJob, ConversionJob
from audio.generation_queue import GenerationQueueWindow

# --- TTS Model Imports ---
from generators.google_cloud_tts import GoogleCloudTTS
from generators.elevenlabs_tts import ElevenLabsTTS
from generators.tts_base import TTSBase

APP_TITLE = "Subtitle Studio"
APP_CONFIG = Path.cwd() / ".subtitle_studio_config.json"
MAX_COL_WIDTH = 450

BUILTIN_REMOVE = [
    (PatternItem(r"^\[[^\]]*\]+$", "", False), "Usuń całe linie [.*]"),
    (PatternItem(r"^\<[^\>]*\>+$", "", False), "Usuń całe linie <.*>"),
    (PatternItem(r"^\{[^\}]*\}+$", "", False), "Usuń całe linie {.*}"),
    (PatternItem(r"^\([^\)]*\)+$", "", False), "Usuń całe linie (.*)"),
    (PatternItem(r"^[A-Z\?\!\.]{,4}$", "", True), None),
    (PatternItem(r" ", "", False), "Usuń niektóre niewidoczne znaki"),
]
BUILTIN_REPLACE = [
    (PatternItem(r"\[[^\]]*\]+", " ", False), "Usuń treść [.*]"),
    (PatternItem(r"\<[^\>]*\>+", " ", False), "Usuń treść <.*>"),
    (PatternItem(r"\{[^\}]*\}+", " ", False), "Usuń treść {.*}"),
    (PatternItem(r"\([^\)]*\)+", " ", False), "Usuń treść (.*)"),
    (PatternItem(r"…", "...", False), "Popraw trójkropek"),
    (PatternItem(r"\.{2,}", ".", False), "Trójkropek > kropka"),
    (PatternItem(r"\?!", "?", False), "?! -> ?"),
    (PatternItem(r"\?{2,}", "?", False), "?(?)+ -> ?"),
    (PatternItem(r"[@#$^&*\(\)\{\}]+", " ", False),
     "Usuń znaki specjalne jak @#$"),
    (PatternItem(r"\s{2,}", " ", False), "Zamień białe znaki na spacje"),
    (PatternItem(r"^[-.\"\']", "", False),
     "Usuń wiodące znaki specjalne (-.\"')"),
    (PatternItem(r"[-\.\"\']$", "", False),
     "Usuń kończące znaki specjalne (-.\"')"),
]

try:
    import pygame

    pygame.mixer.init()
    PYGAME_AVAILABLE = True
except (ImportError, pygame.error) as e:
    print(
        f"Ostrzeżenie: Pygame mixer nie mógł zostać zainicjowany ({e}). Odtwarzanie audio będzie niedostępne.")
    PYGAME_AVAILABLE = False


class SubtitleStudioApp(ctk.CTk):
    """
    Main application class for Subtitle Studio.
    Handles the main window, UI, file operations, project management, and audio interactions.
    """
    APP_VERSION = "0.9.4"

    def __init__(self):
        super().__init__()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.has_unsaved_changes = False

        self.title(APP_TITLE)
        self.geometry("1700x1000")
        try:
            self.iconphoto(False, tk.PhotoImage(
                file=resource_path("assets/icon512.png")))
        except Exception:
            pass

        self.loaded_path: Optional[Path] = None
        self.original_lines: List[str] = []
        self.processed_clean: List[str] = []
        self.processed_replace: List[str] = []

        self.builtin_remove = [PatternItem(
            p.pattern, p.replace, p.case_sensitive, name) for p, name in BUILTIN_REMOVE]
        self.builtin_replace = [PatternItem(
            p.pattern, p.replace, p.case_sensitive, name) for p, name in BUILTIN_REPLACE]
        self.builtin_remove_state = [tk.BooleanVar(value=True, name=f"br_{i}") for i, _ in
                                     enumerate(self.builtin_remove)]
        self.builtin_replace_state = [tk.BooleanVar(value=True, name=f"bp_{i}") for i, _ in
                                      enumerate(self.builtin_replace)]
        for var in self.builtin_remove_state + self.builtin_replace_state:
            var.trace_add("write", self.mark_as_unsaved)
        self.custom_remove: List[PatternItem] = []
        self.custom_replace: List[PatternItem] = []

        self.current_project_path: Optional[Path] = None
        self.project_config = {}
        self.global_config = {}
        self.torch_installed = is_installed('torch')

        self.queue = queue.Queue()
        self.queue_window: Optional[GenerationQueueWindow] = None

        self.audio_dir: Optional[Path] = None
        self.selected_line_index: Optional[int] = None

        self.update_button: Optional[ctk.CTkButton] = None
        self.latest_version_info: Optional[Tuple[str, str]] = None

        self._load_app_config(only_config=True)
        self.apply_theme_settings()
        self._create_menu()
        self._create_widgets()
        self._load_app_config()
        self.check_queue()

        threading.Thread(target=self._check_for_updates, daemon=True).start()

    def mark_as_unsaved(self, *args):
        """Flags the current project as having unsaved changes and updates status."""
        if self.current_project_path:  # Tylko jeśli projekt jest załadowany/zapisany
            self.has_unsaved_changes = True
            if "Gotowy" in self.status.cget("text") and "niezapisane" not in self.status.cget("text"):
                self.set_status(
                    f"{self.status.cget('text')} (niezapisane zmiany)")

    def _create_menu(self):
        """Creates the main application menu bar."""
        menubar = tk.Menu(self)

        config_menu = tk.Menu(menubar, tearoff=0)
        config_menu.add_command(
            label="Otwórz projekt (.json)", command=self.open_project)
        config_menu.add_command(label="Zapisz projekt",
                                command=self.save_project)
        config_menu.add_command(label="Zapisz jako",
                                command=self.save_project_as)
        config_menu.add_separator()
        config_menu.add_command(label="Zamknij projekt",
                                command=self.close_project)
        config_menu.add_separator()
        config_menu.add_command(label="Zamknij", command=self.on_close)
        menubar.add_cascade(label="Projekt", menu=config_menu)

        gen_menu = tk.Menu(menubar, tearoff=0)
        gen_menu.add_command(
            label="Wczytaj napisy", command=self.load_file)

        gen_menu.add_command(
            label="Wybierz katalog audio", command=self.choose_audio_dir)

        gen_menu.add_separator()
        gen_menu.add_command(
            label="Pokaż kolejkę zadań", command=self.show_generation_queue)
        gen_menu.add_command(
            label="Generuj dialogi", command=self.enqueue_generate_all)
        gen_menu.add_command(
            label="Konwertuj audio na ogg", command=self.enqueue_convert_all)

        gen_menu.add_separator()

        gen_menu.add_command(
            label="Dopasuj identyfikatory audio", command=self.open_audio_rename_window)
        gen_menu.add_command(
            label="Usuń wszystkie przekonwertowane pliki (/ready)", command=self.delete_all_converted_audio)

        gen_menu.add_separator()
        gen_menu.add_command(
            label="Pobierz napisy dla Game Reader", command=self.download_clean)
        gen_menu.add_command(
            label="Pobierz napisy dla TTS", command=self.download_replace)
        gen_menu.add_command(
            label="Generuj preset dla Game Reader", command=self.generate_game_reader_preset)

        menubar.add_cascade(label="Dialogi", menu=gen_menu)

        patterns_menu = tk.Menu(menubar, tearoff=0)
        patterns_menu.add_command(
            label="Importuj wzorce z CSV", command=self.import_patterns_from_csv)
        patterns_menu.add_command(
            label="Eksportuj wzorce do CSV", command=self.export_patterns_to_csv)
        patterns_menu.add_separator()
        patterns_menu.add_command(
            label="Usuwanie dialogów", command=self.open_audio_deleter)
        menubar.add_cascade(label="Wzorce", menu=patterns_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(
            label="Ustawienia aplikacji", command=self.open_global_settings)
        settings_menu.add_command(
            label="Ustawienia projektu", command=self.open_project_settings)
        menubar.add_cascade(label="Ustawienia", menu=settings_menu)

        self.config(menu=menubar)

    def _create_widgets(self):
        """Creates and places all main UI widgets in the window."""
        root_grid = ctk.CTkFrame(self)
        root_grid.pack(fill="both", expand=True, padx=10, pady=10)
        root_grid.grid_rowconfigure(0, weight=1)
        # Kolumna 0 (prawy panel) może się rozciągać
        root_grid.grid_columnconfigure(0, weight=1)
        # Kolumna 1 (środkowy panel) ma mieć stałą szerokość - ustawiamy minimalny rozmiar
        root_grid.grid_columnconfigure(1, minsize=500)
        # Kolumna 2 (panel wbudowanych wzorców) nie musi się rozszerzać poziomo
        root_grid.grid_columnconfigure(2, weight=0)

        # --- Preview & Actions ---
        right = ctk.CTkFrame(root_grid)
        right.grid(row=0, column=0, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(4, weight=1)

        # Stats and Apply button
        stats_frame = ctk.CTkFrame(right)
        stats_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkButton(stats_frame, text="Zastosuj wzorce",
                      command=self.apply_processing).pack(side="left", padx=5)

        self.update_button = ctk.CTkButton(stats_frame, text="Nowa wersja!",
                                           command=self._download_update,
                                           fg_color="#006400", hover_color="#004d00")  # Ciemna zieleń
        self.update_button.pack(side="left", padx=5)
        self.update_button.pack_forget()
        self.lbl_filename = ctk.CTkLabel(
            stats_frame, text="Brak wczytanego pliku")
        self.lbl_filename.pack(side="left", anchor="w", padx=5)

        self.lbl_count_orig = ctk.CTkLabel(stats_frame, text="Linie org.: 0")
        self.lbl_count_orig.pack(side="right", anchor="w", padx=5)
        self.lbl_count_after = ctk.CTkLabel(stats_frame, text="Linie po: 0")
        self.lbl_count_after.pack(side="right", anchor="w", padx=5)
        self.lbl_count_words = ctk.CTkLabel(stats_frame, text="Słowa: 0")
        self.lbl_count_words.pack(side="right", anchor="w", padx=5)
        self.lbl_count_chars = ctk.CTkLabel(stats_frame, text="Znaki: 0")
        self.lbl_count_chars.pack(side="right", anchor="w", padx=5)

        # Audio buttons
        audio_btn_frame = ctk.CTkFrame(right)
        audio_btn_frame.grid(
            row=2, column=0, sticky="ew", pady=(0, 5), padx=5)  # Row 2

        self.play_button = ctk.CTkButton(audio_btn_frame, text="▶️ Odtwórz", width=80, command=self.play_selected_audio,
                                         state="disabled")
        self.play_button.pack(side="left", padx=(0, 4))

        self.audio_select_var = tk.StringVar(value="(brak plików)")
        self.audio_select = ctk.CTkOptionMenu(
            audio_btn_frame, variable=self.audio_select_var, values=["(brak plików)"])
        self.audio_select.pack(side="left", padx=(4, 8))

        if not PYGAME_AVAILABLE:
            self.play_button.configure(state="disabled", text="N/A Pygame")

        self.generate_button = ctk.CTkButton(audio_btn_frame, text="⚙️ Generuj", width=80,
                                             command=self.enqueue_generate_single, state="disabled")
        self.generate_button.pack(side="left", padx=4)
        self.edit_line_button = ctk.CTkButton(audio_btn_frame, text="✏️ Edytuj linię", width=80,
                                              command=self.add_replace_pattern_from_selection, state="disabled")
        self.edit_line_button.pack(side="left", padx=4)

        self.delete_button = ctk.CTkButton(audio_btn_frame, text="❌ Usuń", width=80, command=self.delete_selected_audio,
                                           state="disabled")
        self.delete_button.pack(side="left", padx=4)

        self.delete_all_button = ctk.CTkButton(audio_btn_frame, text="🗑️ Usuń Wsz.", width=80,
                                               command=self.delete_all_selected_audio, state="disabled")
        self.delete_all_button.pack(side="left", padx=4)

        # Search bar
        search_frame = ctk.CTkFrame(right)
        search_frame.grid(
            row=3, column=0, sticky="ew", pady=(0, 5), padx=5)  # Row 3
        search_frame.grid_columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(
            search_frame, placeholder_text="Przeszukaj podgląd")
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Return>", lambda event: self.apply_patterns())
        self.search_entry.bind(
            "<Control-BackSpace>", lambda event: self.search_entry.delete(0, tk.END))

        self.search_button = ctk.CTkButton(
            search_frame, text="Szukaj", command=self.apply_patterns)
        self.search_button.grid(row=0, column=1, padx=(6, 0))

        # Preview Textbox
        self.txt_preview = ctk.CTkTextbox(right)
        self.txt_preview.grid(
            row=4, column=0, sticky="nsew", padx=5, pady=(0, 5))  # Row 4
        self.txt_preview.configure(state=tk.DISABLED)
        self.txt_preview.tag_config(
            "selected_line", background="gray25", foreground="white")
        self.txt_preview.bind("<ButtonRelease-1>", self.on_preview_click)
        self.txt_preview.bind("<Double-Button-1>", self.play_selected_audio)
        self.txt_preview.bind("<Control-Button-1>",
                              self.add_replace_pattern_from_selection)
        self.txt_preview.bind(
            "<Delete>", self.add_remove_pattern_from_selection)
        self.txt_preview.configure(cursor="hand2")

        self.center_frame = ctk.CTkFrame(root_grid, width=450)
        try:
            self.center_frame.grid_propagate(False)
        except Exception:
            pass

        self.center_frame.grid_columnconfigure(0, weight=1)
        self.center_frame.grid(row=0, column=1, sticky="ns", padx=(0, 10))
        self.center_frame.grid_rowconfigure(1, weight=1)
        self.center_frame.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(self.center_frame, text="Własne wzorce wycinające").grid(
            row=0, column=0, sticky="w", padx=6)
        self.custom_remove_frame = ctk.CTkScrollableFrame(self.center_frame)
        self.custom_remove_frame.grid(
            row=1, column=0, sticky="nsew", padx=6, pady=(2, 6))

        remove_btn_frame = ctk.CTkFrame(self.center_frame)
        remove_btn_frame.grid(row=2, column=0, sticky="ew", padx=6, pady=4)
        remove_btn_frame.grid_columnconfigure(0, weight=1)
        remove_btn_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(remove_btn_frame, text="Dodaj wzorzec", command=self.open_add_remove_pattern).grid(
            row=0, column=0, sticky="ew", padx=(0, 2))
        ctk.CTkButton(remove_btn_frame, text="Wyczyść listę", command=lambda: self._clear_custom_list('remove'),
                      fg_color="gray").grid(row=0, column=1, sticky="ew", padx=(2, 0))

        replace_top_frame = ctk.CTkFrame(self.center_frame)
        replace_top_frame.grid(row=3, column=0, sticky="ew", pady=(4, 4))
        lab_rep = ctk.CTkLabel(replace_top_frame,
                               text="Własne wzorce podmieniające")
        lab_rep.pack(side="left", anchor="w", fill="x", expand=False, padx=6)

        self.custom_replace_frame = ctk.CTkScrollableFrame(self.center_frame)
        self.custom_replace_frame.grid(
            row=4, column=0, sticky="nsew", padx=6, pady=(2, 6))

        replace_btn_frame = ctk.CTkFrame(self.center_frame)
        replace_btn_frame.grid(row=5, column=0, sticky="ew", padx=6, pady=4)
        replace_btn_frame.grid_columnconfigure(0, weight=1)
        replace_btn_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(replace_btn_frame, text="Dodaj wzorzec", command=self.open_add_replace_pattern).grid(
            row=0, column=0, sticky="ew", padx=(0, 2))
        ctk.CTkButton(replace_btn_frame, text="Wyczyść listę", command=lambda: self._clear_custom_list('replace'),
                      fg_color="gray").grid(row=0, column=1, sticky="ew", padx=(2, 0))

        builtin_frame = ctk.CTkFrame(root_grid, width=MAX_COL_WIDTH)
        builtin_frame.grid(row=0, column=2, sticky="nsew", padx=(0, 10))
        builtin_frame.grid_columnconfigure(0, weight=1)
        builtin_frame.grid_rowconfigure(2, weight=1)
        builtin_frame.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(builtin_frame, text="Wbudowane wzorce wycinające").grid(
            row=1, column=0, sticky="we", padx=6)
        self._create_builtin_list(
            builtin_frame, self.builtin_remove, self.builtin_remove_state, 2)

        ctk.CTkLabel(builtin_frame, text="Wbudowane wzorce podmieniające").grid(
            row=3, column=0, sticky="we", padx=6)
        self._create_builtin_list(
            builtin_frame, self.builtin_replace, self.builtin_replace_state, 4)

        # --- Status Bar ---
        self.status = ctk.CTkLabel(self, text="Gotowy", anchor="w")
        self.status.pack(fill="x", side="bottom", padx=10, pady=(0, 5))

    def build_clean_list_frame(self, parent_frame, row_nr) -> CTkFrame:
        """Helper to create a standard input frame for patterns."""
        frame = ctk.CTkFrame(parent_frame)
        frame.grid(row=row_nr, column=0, sticky="ew", pady=(4, 4))
        return frame

    def build_scroll_list_frame(self, parent_frame, row_nr) -> CTkScrollableFrame:
        """Helper to create a standard scrollable frame."""
        frame = ctk.CTkScrollableFrame(parent_frame)
        frame.grid(row=row_nr, column=0, sticky="nsew", padx=6, pady=(2, 6))
        return frame

    def _create_builtin_list(self, parent, patterns, states, row_nr):
        """Populates a scrollable frame with built-in pattern checkboxes."""
        sc = ctk.CTkScrollableFrame(parent)
        sc.grid(row=row_nr, column=0, sticky="nsew", padx=6, pady=(0, 6))
        for i, p in enumerate(patterns):
            text = f"{p.pattern} -> {p.replace}" if p.name is None else p.name
            cb = ctk.CTkCheckBox(sc, text=text, variable=states[i])
            cb.pack(anchor="w", pady=2)

    def open_add_remove_pattern(self):
        """Otwiera okno dodawania nowego wzorca wycinającego."""
        PatternEditorWindow(
            self,
            pattern_type='remove',
            callback=self.handle_pattern_update,
            existing_pattern=None
        )

    def open_add_replace_pattern(self):
        """Otwiera okno dodawania nowego wzorca podmieniającego."""
        PatternEditorWindow(
            self,
            pattern_type='replace',
            callback=self.handle_pattern_update,
            existing_pattern=None
        )

    def open_edit_pattern(self, pattern: PatternItem, target_list: List[PatternItem]):
        """Otwiera okno edycji dla istniejącego wzorca."""
        pattern_type = 'remove' if target_list is self.custom_remove else 'replace'

        # Przekaż *oryginalny* wzorzec do edytora.
        # Użytkownik edytuje regex, więc powinien widzieć regex.
        PatternEditorWindow(
            self,
            pattern_type=pattern_type,
            callback=self.handle_pattern_update,
            existing_pattern=pattern
        )

    def handle_pattern_update(self, new_pattern: PatternItem, old_pattern: Optional[PatternItem], pattern_type: str):
        """
        Callback z PatternEditorWindow. Aktualizuje listę wzorców.
        """
        target_list = self.custom_remove if pattern_type == 'remove' else self.custom_replace

        if old_pattern:
            # Tryb edycji: znajdź stary i zastąp
            try:
                index = target_list.index(old_pattern)
                target_list[index] = new_pattern
            except ValueError:
                # Nie znaleziono (nie powinno się zdarzyć), po prostu dodaj
                target_list.append(new_pattern)
                print(
                    f"Ostrzeżenie: Nie znaleziono wzorca '{old_pattern.pattern}' do edycji. Dodano jako nowy.")
        else:
            # Tryb dodawania
            target_list.append(new_pattern)

        self._refresh_custom_lists()
        self.mark_as_unsaved()
        self.set_status("Zaktualizowano wzorce.")

    def add_row(self, frame, pattern_item: PatternItem, target_list: List[PatternItem]):
        """Adds a UI row for a pattern."""
        row = ctk.CTkFrame(frame)
        row.pack(fill="x", pady=2, padx=2)

        def on_edit_click(event):
            # Sprawdź, czy wciśnięty jest klawisz Control (maska 0x0004)
            if event.state & 0x0004:
                self.open_edit_pattern(pattern_item, target_list)

        row.bind("<Button-1>", on_edit_click)
        row.bind("<Double-Button-1>", on_edit_click)

        def on_delete():
            try:
                target_list.remove(pattern_item)
            except ValueError:
                pass
            row.destroy()
            self.mark_as_unsaved()

        def on_edit():
            self.open_edit_pattern(pattern_item, target_list)

        btnEdit = ctk.CTkButton(row, text="Edytuj", width=60, command=on_edit)
        btnEdit.pack(side="left", padx=4)
        btnX = ctk.CTkButton(row, text="X", width=60, command=on_delete)
        btnX.pack(side="left", padx=4)

        lbl_text = f"{'' if not pattern_item.case_sensitive else '(Aa)'} [{pattern_item.pattern}] -> [{pattern_item.replace}]"
        lbl = ctk.CTkLabel(row, text=lbl_text)
        lbl.pack(side="left", fill="x", expand=False, padx=4)
        lbl.bind("<Button-1>", on_edit_click)

    def _clear_custom_list(self, pattern_type: str):
        """Usuwa wszystkie wzorce z wybranej listy (remove lub replace)."""
        target_list = self.custom_remove if pattern_type == 'remove' else self.custom_replace
        list_name = "wycinających" if pattern_type == 'remove' else "podmieniających"

        if not target_list:
            messagebox.showinfo(
                "Lista jest pusta", f"Lista wzorców {list_name} jest już pusta.", parent=self)
            return

        if messagebox.askyesno("Potwierdź",
                               f"Czy na pewno chcesz usunąć WSZYSTKIE ({len(target_list)}) wzorce z listy '{list_name}'?",
                               parent=self):
            target_list.clear()
            self._refresh_custom_lists()
            self.mark_as_unsaved()
            self.set_status(f"Wyczyszczono listę wzorców {list_name}.")

    def load_file(self, path: Optional[str] = None, bypass_save_check: bool = False):
        """Loads a subtitle .txt file."""
        if not path:
            initial_dir = self.global_config.get(
                'start_directory') or self._get_save_dir()
            path = filedialog.askopenfilename(title="Wybierz plik napisów",
                                              filetypes=[
                                                  ("Text files", "*.txt"), ("All files", "*")],
                                              initialdir=initial_dir)
        if not path:
            return
        if not bypass_save_check and not self._check_unsaved_changes():
            return

        self.loaded_path = Path(path)
        if not self.current_project_path:
            self.lbl_filename.configure(text=str(self.loaded_path.name))
        try:
            with open(self.loaded_path, "r", encoding="utf-8", errors="replace") as f:
                self.original_lines = f.read().splitlines()
            self.apply_patterns()
            self.set_status(f"Wczytano {len(self.original_lines)} linii")
            # Po wczytaniu pliku nie ma niezapisanych zmian *projektu*
            self.has_unsaved_changes = False
            # Zaktualizuj ścieżkę w configu projektu, jeśli jest otwarty
            if self.current_project_path:
                # To wywoła zapis
                self.set_project_config(
                    'subtitle_path', str(self.loaded_path))

        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się wczytać pliku:\n{e}")

    def open_project(self, path: str | None = None):
        """Opens a .json project file."""
        if path is None:
            if not self._check_unsaved_changes():
                return
            initial_dir = self.global_config.get(
                'start_directory') or str(Path.cwd())
            path = filedialog.askopenfilename(title="Otwórz projekt",
                                              filetypes=[
                                                  ("JSON", "*.json"), ("All", "*")],
                                              initialdir=initial_dir)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.current_project_path = Path(path)
            self.project_config = cfg

            all_vars = self.builtin_remove_state + self.builtin_replace_state
            traces = {}
            for var in all_vars:
                if var.trace_info():
                    trace_id = var.trace_info()[0][1]
                    # Zapisz var i trace_id pod nazwą
                    traces[var._name] = (var, trace_id)
                    var.trace_remove("write", trace_id)

            for i, val in enumerate(cfg.get("builtin_remove_state", [])):
                if i < len(self.builtin_remove_state):
                    self.builtin_remove_state[i].set(bool(val))
            for i, val in enumerate(cfg.get("builtin_replace_state", [])):
                if i < len(self.builtin_replace_state):
                    self.builtin_replace_state[i].set(bool(val))

            for name, (var, trace_id) in traces.items():
                var.trace_add("write", self.mark_as_unsaved)

            self.custom_remove = [PatternItem.from_json(
                x) for x in cfg.get("custom_remove", [])]
            self.custom_replace = [PatternItem.from_json(
                x) for x in cfg.get("custom_replace", [])]
            self._refresh_custom_lists()

            subtitle_path = cfg.get("subtitle_path")
            if subtitle_path and Path(subtitle_path).exists():
                self.load_file(subtitle_path, bypass_save_check=True)
            else:
                self.original_lines = []
                self.apply_patterns()
                self.lbl_filename.configure(text="Brak wczytanego pliku")

            audio_path_str = cfg.get("audio_path")
            self.audio_dir = Path(audio_path_str) if audio_path_str else None

            self.set_status(
                f"Wczytano projekt: {self.current_project_path.name}")
            self.save_app_setting('last_project', path)
            self.has_unsaved_changes = False  # Świeżo załadowany
            self.lbl_filename.configure(text=os.path.basename(path))
        except Exception as e:
            messagebox.showerror(
                "Błąd wczytywania projektu", f"Nie udało się wczytać konfiguracji:\n{e}")
            self.current_project_path = None
            self.project_config = {}
            self.has_unsaved_changes = False

    def close_project(self):
        """Closes the current project and restarts."""
        if not self._check_unsaved_changes():
            return
        try:
            self.save_app_setting('last_project', None)
            self._reset_app_state()
            os.execl(sys.executable, sys.executable, *sys.argv)
        except Exception as e:
            messagebox.showerror(
                "Błąd restartu", f"Nie udało się zrestartować aplikacji:\n{e}")

    def _reset_app_state(self):
        """Resets the application state to default."""
        self.current_project_path = None
        self.project_config = {}
        self.original_lines = []
        self.processed_clean = []
        self.processed_replace = []
        self.custom_remove = []
        self.custom_replace = []
        self.loaded_path = None
        self.audio_dir = None
        self.has_unsaved_changes = False
        self._refresh_custom_lists()
        self.apply_patterns()
        self.lbl_filename.configure(text="Brak wczytanego pliku")
        # Zresetuj wbudowane checkboxy (opcjonalne)
        for var in self.builtin_remove_state + self.builtin_replace_state:
            var.set(True)

    def set_project_config(self, param, value):
        """Saves a single key-value pair to the current project config."""
        if self.project_config is None:
            self.project_config = {}
        # Zapisuj tylko jeśli jest zmiana
        if self.project_config.get(param) != value:
            self.project_config[param] = value
            self.mark_as_unsaved()
            if self.current_project_path:
                self.save_project()

    def save_project(self, cfg: dict | None = None):
        """Saves the current config to the loaded project file."""
        if not self.current_project_path:
            return self.save_project_as()

        final_cfg = self._gather_project_config()
        if cfg:
            final_cfg.update(cfg)
        self.project_config = final_cfg

        try:
            with open(self.current_project_path, "w", encoding="utf-8") as f:
                json.dump(final_cfg, f, indent=2, ensure_ascii=False)
            self.set_status(
                f"Zapisano projekt: {self.current_project_path.name}")
            self.has_unsaved_changes = False
        except Exception as e:
            messagebox.showerror(
                "Błąd", f"Nie udało się zapisać konfiguracji:\n{e}")

    def save_project_as(self):
        """Saves the current configuration to a new .json project file."""
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=self.global_config.get('start_directory') or str(
                self.current_project_path.parent if self.current_project_path else Path.cwd())
        )
        if not path:
            return
        self.current_project_path = Path(path)
        self.save_project()

    def _gather_project_config(self) -> dict:
        """Collects all current project settings."""
        current_cfg = self.project_config.copy() if self.project_config else {}
        current_cfg.update({
            "builtin_remove_state": [bool(v.get()) for v in self.builtin_remove_state],
            "builtin_replace_state": [bool(v.get()) for v in self.builtin_replace_state],
            "custom_remove": [p.to_json() for p in self.custom_remove],
            "custom_replace": [p.to_json() for p in self.custom_replace],
            "subtitle_path": str(self.loaded_path) if self.loaded_path else None,
            "audio_path": str(self.audio_dir.absolute()) if self.audio_dir else None,
            "active_tts_model": self.project_config.get('active_tts_model', 'XTTS'),
            "base_audio_speed": self.project_config.get('base_audio_speed', 1.1)
        })
        return current_cfg

    def _load_app_config(self, only_config=False):
        """Loads the global app config."""
        if APP_CONFIG.exists():
            try:
                with open(APP_CONFIG, "r", encoding="utf-8") as f:
                    self.global_config = json.load(f)
                    if only_config:
                        return
                last_proj = self.global_config.get('last_project')
                # Sprawdź czy plik projektu nadal istnieje
                if last_proj and Path(last_proj).exists():
                    self.open_project(last_proj)
                else:
                    # Jeśli nie istnieje, usuń wpis
                    if last_proj:
                        self.save_app_setting('last_project', None)
                    self._reset_app_state()
                self.global_config.setdefault('appearance_mode', 'System')
                self.global_config.setdefault('color_theme', 'blue')

            except Exception as e:
                print(f"Błąd wczytywania konfiguracji aplikacji: {e}")
                self.global_config = {}

    def filter_preview(self, lines: List[str]) -> List[str]:
        """Filters preview lines based on search."""
        search_term = self.search_entry.get()
        if not search_term:
            return lines
        try:
            # Użyj re.escape, aby traktować wyszukiwany tekst dosłownie, chyba że to regex
            # Prostsze: po prostu szukaj podciągu, ignorując wielkość liter
            pattern = search_term.lower()
            return [line for line in lines if pattern in line.lower()]
        except re.error:
            # Jeśli wprowadzono nieprawidłowy regex, po prostu nie filtruj
            return lines

    def _refresh_custom_lists(self):
        """Recreates the custom pattern UI lists."""
        for frame_attr in ['custom_remove_frame', 'custom_replace_frame']:
            if hasattr(self, frame_attr):
                widget = getattr(self, frame_attr)
                if widget:
                    # Usuń dzieci przed zniszczeniem ramki
                    for child in widget.winfo_children():
                        child.destroy()
                    widget.destroy()
        self.custom_remove_frame = self.build_scroll_list_frame(
            self.center_frame, 1)
        for p in self.custom_remove:
            self.add_row(self.custom_remove_frame, p, self.custom_remove)

        self.custom_replace_frame = self.build_scroll_list_frame(
            self.center_frame, 4)  # Poprawiony row
        for p in self.custom_replace:
            self.add_row(self.custom_replace_frame, p, self.custom_replace)

    def _gather_active_patterns(self) -> tuple[List[PatternItem], List[PatternItem]]:
        """Collects all active built-in and custom patterns."""
        remove_patterns = list(self.custom_remove)  # Kopiuj listę
        remove_patterns.extend(
            p for i, p in enumerate(self.builtin_remove) if self.builtin_remove_state[i].get())

        replace_patterns = list(self.custom_replace)  # Kopiuj listę
        replace_patterns.extend(
            p for i, p in enumerate(self.builtin_replace) if self.builtin_replace_state[i].get())

        return remove_patterns, replace_patterns

    def apply_processing(self):
        """Applies all active patterns to the loaded subtitles."""
        if not self.original_lines:
            messagebox.showwarning(
                'Brak pliku', 'Najpierw wczytaj plik z napisami.')
            return

        self.apply_patterns()  # To zaktualizuje processed_clean i processed_replace

        self.set_status('Przetworzono napisy — gotowe do pobrania')
        self.mark_as_unsaved()

    def download_clean(self):
        """Saves the 'clean' (for Game Reader) subtitles to a file."""
        if not self.processed_clean:
            messagebox.showwarning(
                'Brak danych', 'Brak oczyszczonych linii. Najpierw przetwórz plik.', parent=self)
            return
        path = filedialog.asksaveasfilename(title='Zapisz oczyszczone napisy', defaultextension='.txt',
                                            filetypes=[
                                                ('Text files', '*.txt')],
                                            initialdir=self._get_save_dir())
        if not path:
            return
        self._save_lines_to_file(path, self.processed_clean, "oczyszczone")

    def download_replace(self):
        """Saves the 'replaced' (for TTS) subtitles to a file."""
        if not self.processed_replace:
            messagebox.showwarning(
                'Brak danych', 'Brak zamienionych linii. Najpierw przetwórz plik.', parent=self)
            return
        path = filedialog.asksaveasfilename(title='Zapisz napisy z podmianami', defaultextension='.txt',
                                            filetypes=[
                                                ('Text files', '*.txt')],
                                            initialdir=self._get_save_dir())
        if not path:
            return
        self._save_lines_to_file(path, self.processed_replace, "z podmianami")

    def _get_save_dir(self) -> str | None:
        """Determines the initial directory for save dialogs."""
        if self.loaded_path:
            return str(self.loaded_path.parent)
        return self.global_config.get('start_directory')

    def _save_lines_to_file(self, path: str, lines: List[str], description: str):
        """Helper function to write lines to a text file."""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            messagebox.showinfo(
                'Gotowe', f'Zapisano napisy {description}:\n{path}', parent=self)
            self.set_status(
                f'Zapisano napisy {description}: {Path(path).name}')
        except Exception as e:
            messagebox.showerror('Błąd zapisu', str(e), parent=self)

    def apply_patterns(self):
        """Recalculates processed lines and updates preview."""
        self.lbl_count_orig.configure(
            text=f'Linie org.: {len(self.original_lines):,}'.replace(",", " "))
        rem_patterns, rep_patterns = self._gather_active_patterns()

        try:
            self.processed_clean = apply_remove_patterns(
                self.original_lines, rem_patterns)
            self.processed_replace = apply_replace_patterns(
                self.processed_clean, rep_patterns)
        except re.error as e:
            messagebox.showerror(
                'Błąd regex', f'Błąd w wyrażeniu regularnym:\n{e}')
            return
        except Exception as e:
            messagebox.showerror(
                'Błąd przetwarzania', f'Wystąpił nieoczekiwany błąd podczas stosowania wzorców:\n{e}')
            return

        total_words = sum(len(line.split())
                          for line in self.processed_replace)
        total_chars = sum(len(line) for line in self.processed_replace)

        self.lbl_count_after.configure(
            text=f'Linie po: {len(self.processed_clean):,}'.replace(",", " "))
        self.lbl_count_words.configure(
            text=f'Słowa: {total_words:,}'.replace(",", " "))
        self.lbl_count_chars.configure(
            text=f'Znaki: {total_chars:,}'.replace(",", " "))

        self.lbl_count_after.configure(
            text=f'Linie po: {len(self.processed_clean):,}'.replace(",", " "))
        self.set_preview(self.processed_replace)
        self.update_audio_buttons_state()

    def set_preview(self, lines_to_show: list[str]):
        """Updates the read-only preview text box with numbered lines."""
        # Zresetuj zaznaczenie
        self.selected_line_index = None
        self.txt_preview.tag_remove("selected_line", "1.0", tk.END)

        total_lines = len(lines_to_show)
        num_digits = len(str(total_lines)) if total_lines > 0 else 1
        numbered_lines = [
            f"{str(i + 1).zfill(num_digits)} | {line}"
            for i, line in enumerate(lines_to_show)
        ]

        filtered = self.filter_preview(numbered_lines)

        self.txt_preview.configure(state='normal')
        self.txt_preview.delete('1.0', tk.END)  # Zaczynaj od 1.0
        if filtered:
            self.txt_preview.insert('1.0', '\n'.join(filtered))
        self.txt_preview.configure(state='disabled')

    def set_status(self, txt: str):
        """Updates status bar."""
        self.status.configure(text=txt)

    def open_audio_deleter(self):
        """Opens Batch Audio Deleter window."""
        if not self.processed_replace:
            return messagebox.showwarning("Brak danych", "Najpierw przetwórz.", parent=self)
        if not self.audio_dir:
            return messagebox.showwarning("Brak katalogu", "Ustaw katalog audio.", parent=self)
        win = AudioDeleterWindow(
            self, self.processed_replace, str(self.audio_dir))
        win.grab_set()

    def open_global_settings(self):
        """Opens the Global Settings window."""
        win = SettingsWindow(self, self.torch_installed, mode='global')
        win.grab_set()

    def open_project_settings(self):
        """Opens the Project Settings window."""
        if not self.current_project_path:
            return messagebox.showwarning("Brak projektu", "Otwórz lub zapisz projekt.", parent=self)
        win = SettingsWindow(self, self.torch_installed, mode='project')
        win.grab_set()

    def generate_game_reader_preset(self):
        """
        Generates a folder structure and config file (clean.json)
        compatible with the "Game Reader" application.
        """
        if not self.processed_clean:
            messagebox.showwarning('Brak danych',
                                   'Brak oczyszczonych napisów (dla Game Reader). Najpierw przetwórz plik.',
                                   parent=self)
            return

        if not self.audio_dir or not (self.audio_dir / "ready").is_dir():
            messagebox.showwarning('Brak audio',
                                   'Katalog audio z podkatalogiem "ready" nie jest ustawiony lub nie istnieje.',
                                   parent=self)
            return

        # 1. Get destination folder
        initial_dir = self._get_save_dir()
        dest_folder_path = filedialog.askdirectory(
            title="Wybierz folder docelowy dla presetu",
            initialdir=initial_dir,
            parent=self
        )
        if not dest_folder_path:
            return

        dest_folder = Path(dest_folder_path)

        # 2. Ask to copy audio
        copy_audio = messagebox.askyesno(
            "Kopiowanie audio",
            "Czy skopiować przetworzone pliki audio (z /ready) do nowego folderu presetu (do podkatalogu /audio)?\n\n"
            "Wybierz 'Tak', aby utworzyć w pełni samodzielny preset.\n"
            "Wybierz 'Nie', aby preset odwoływał się do bieżącego katalogu /ready.",
            parent=self
        )

        # 3. Load template clean.json (z pliku dostarczonego przez użytkownika)
        preset_template = {
            "monitor": {"top": 900, "left": 375, "width": 1170, "height": 120},
            "resolution": "1920x1080",
            "CENTER_LINE_MARGIN": 100,
            "CENTER_LINE_2_START": 1,
            "CENTER_LINE_3_START_RATIO": 0.3,
            "RESOLUTION_DOWNSCALE": 0.45,
            "CAPTURE_INTERVAL": 0.5,
            "MIN_HEIGHT": 10,
            "MAX_HEIGHT": 100,
            "ENABLE_REMOVE_CHARACTER_NAME": False,
            "ENABLE_SCREENSHOTS": False,
            "USE_CENTER_LINE_1": False,
            "USE_CENTER_LINE_2": False,
            "USE_CENTER_LINE_3": False,
            "audio_dir": "",  # To be filled
            "text_file_path": "",  # To be filled
            "names_file_path": "",
            "screenshot_dir": "",
            "key_bindings": {
                "toggle_on": "home", "toggle_off": "end", "volume_up": "page_up",
                "volume_down": "page_down", "switch_monitor_prev": "alt+1",
                "switch_monitor_next": "alt+2", "test_sound": "insert",
                "open_settings": "alt+`", "interrupt_audio": "delete"
            },
            "monitor2_enabled": False,
            "monitor2_top": 100, "monitor2_left": 375, "monitor2_width": 1170, "monitor2_height": 120
        }

        # 4. Define paths
        text_filename = "subtitles.txt"
        text_file_dest_path = dest_folder / text_filename
        json_file_dest_path = dest_folder / "preset.json"
        source_audio_path = self.audio_dir / "ready"

        try:
            # 5. Save text file (bez pokazywania komunikatu)
            with open(text_file_dest_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(self.processed_clean))
            preset_template["text_file_path"] = str(
                text_file_dest_path.absolute())

            # 6. Handle audio
            if copy_audio:
                audio_dest_folder = dest_folder / "audio"

                # Ensure target dir exists and is empty if it exists
                if audio_dest_folder.exists():
                    print(f"Usuwam istniejący folder: {audio_dest_folder}")
                    shutil.rmtree(audio_dest_folder)

                # Copy
                print(f"Kopiuję {source_audio_path} do {audio_dest_folder}")
                shutil.copytree(str(source_audio_path), str(audio_dest_folder))

                preset_template["audio_dir"] = str(
                    audio_dest_folder.absolute())
            else:
                # Use absolute path to existing /ready dir
                preset_template["audio_dir"] = str(
                    source_audio_path.absolute())

            # 7. Save clean.json
            with open(json_file_dest_path, "w", encoding="utf-8") as f:
                json.dump(preset_template, f, indent=4, ensure_ascii=False)

            messagebox.showinfo(
                "Preset wygenerowany",
                f"Pomyślnie wygenerowano preset dla Game Reader w folderze:\n{dest_folder_path}",
                parent=self
            )

        except Exception as e:
            messagebox.showerror("Błąd generowania presetu",
                                 f"Wystąpił błąd:\n{e}", parent=self)

    # *** Koniec nowej metody ***

    def import_patterns_from_csv(self):
        """Imports 'replace' patterns from CSV."""
        initial_dir = self.global_config.get(
            'start_directory') or self._get_save_dir()
        file_path = filedialog.askopenfilename(
            title="Wybierz plik CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=initial_dir
        )
        if not file_path:
            return

        imported_count = 0
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if not row or len(row) < 2:
                        print(
                            f"Pominięto wiersz {i + 1}: za mało kolumn ({len(row)})")
                        continue

                    # .strip() jest nadal OK, csv.reader zajmie się cudzysłowami
                    pattern = row[0].strip()
                    if not pattern:
                        print(f"Pominięto wiersz {i + 1}: pusty wzorzec")
                        continue
                    try:
                        re.compile(pattern)
                    except re.error as e:
                        print(
                            f"Pominięto wiersz {i + 1}: Niepoprawny regex '{pattern}'. Błąd: {e}")
                        continue

                    replace = row[1].strip() if len(row) > 1 else ""
                    case_sensitive = True
                    if len(row) > 2 and row[2].strip().isdigit():
                        case_sensitive = not bool(int(row[2].strip()))

                    new_pattern = PatternItem(pattern, replace, case_sensitive)
                    self.custom_replace.append(new_pattern)
                    self.add_row(self.custom_replace_frame,
                                 new_pattern, self.custom_replace)
                    imported_count += 1

            if imported_count > 0:
                self.mark_as_unsaved()
                messagebox.showinfo(
                    "Import zakończony", f"Zaimportowano {imported_count} wzorców.")
            else:
                messagebox.showwarning(
                    "Import zakończony", "Nie zaimportowano żadnych poprawnych wzorców.")
        except Exception as e:
            messagebox.showerror(
                "Błąd importu", f"Nie udało się zaimportować pliku:\n{e}")

    def save_global_config(self, new_config_data: dict):
        """Saves data to the global .subtitle_studio_config.json file."""
        self.global_config.update(new_config_data)
        try:
            with open(APP_CONFIG.absolute(), "w", encoding="utf-8") as f:
                json.dump(self.global_config, f, indent=2)
        except Exception as e:
            messagebox.showerror("Błąd zapisu config", f"Błąd: {e}")

    def save_app_setting(self, param, value):
        """Saves a single key-value to global config."""
        self.save_global_config({param: value})

    def _check_unsaved_changes(self) -> bool:
        """
        Checks for unsaved changes and prompts the user to save if necessary.

        Returns:
            bool: False if the action was cancelled, True otherwise.
        """
        if self.has_unsaved_changes and self.current_project_path:
            msg = "Masz niezapisane zmiany w projekcie. Czy chcesz je zapisać?"
            result = messagebox.askyesnocancel(
                "Niezapisane zmiany", msg, parent=self)

            if result is True:
                self.save_project()
            elif result is None:
                return False
        return True

    def on_close(self):
        """Handles window close event."""
        if self._check_unsaved_changes():
            self.stop_audio()
            self.quit()

    # ===============================
    # === AUDIO UI METHODS        ===
    # ===============================
    def on_preview_click(self, event):
        """Handles clicks inside the preview textbox to select a line."""
        try:
            # Pobierz indeks kliknięcia (np. "5.10")
            click_index = self.txt_preview.index(f"@{event.x},{event.y}")
            # Pobierz numer linii (np. "5")
            line_number_str = click_index.split('.')[0]
            # Przekonwertuj na indeks listy (0-based)
            # Uwaga: To jest indeks linii W WIDOCZNYM, filtrowanym tekście!
            visible_line_index = int(line_number_str) - 1

            # Musimy zmapować ten widoczny indeks na oryginalny indeks z `processed_replace`
            # Najpierw pobierz WSZYSTKIE linie z textboxa
            all_visible_lines = self.txt_preview.get(
                "1.0", tk.END).splitlines()
            if visible_line_index >= len(all_visible_lines):
                return  # Kliknięcie poza tekstem

            # Pobierz treść klikniętej linii (np. "005 | Jakiś tekst")
            clicked_line_content = all_visible_lines[visible_line_index]

            # Wyciągnij numer oryginalnej linii z początku
            match = re.match(r"^\s*(\d+)\s*\|", clicked_line_content)
            if match:
                original_line_number = int(match.group(1))
                self.selected_line_index = original_line_number - 1  # 0-based index

                # Podświetl linię
                self.txt_preview.tag_remove("selected_line", "1.0", tk.END)
                line_start = f"{line_number_str}.0"
                line_end = f"{line_number_str}.end"
                self.txt_preview.tag_add("selected_line", line_start, line_end)

            else:
                # Nie udało się sparsować numeru linii (np. pusta linia, błąd formatowania)
                self.selected_line_index = None
                self.txt_preview.tag_remove("selected_line", "1.0", tk.END)

        except (ValueError, tk.TclError):
            # Błąd konwersji lub indeksu - kliknięcie w złym miejscu
            self.selected_line_index = None
            self.txt_preview.tag_remove("selected_line", "1.0", tk.END)

        # Zaktualizuj stan przycisków
        self.update_audio_buttons_state()

    def update_audio_buttons_state(self):
        """Enables/disables audio action buttons based on selection and audio dir."""
        line_selected = self.selected_line_index is not None
        audio_dir_set = self.audio_dir is not None and self.audio_dir.is_dir()

        project_loaded = self.current_project_path is not None
        lines_processed = bool(self.processed_replace)

        # Znajdź pliki dla zaznaczonej linii (jeśli jest)
        files_exist = False
        if line_selected and audio_dir_set:
            identifier = str(self.selected_line_index + 1)
            found_files = self._find_audio_files(identifier)
            files_exist = bool(found_files)

            if found_files:
                file_names = [f.name for f, _ in found_files]
                self.audio_select.configure(values=file_names)
                self.audio_select_var.set(file_names[0])
            else:
                self.audio_select.configure(values=["(brak plików)"])
                self.audio_select_var.set("(brak plików)")

        # Ustaw stany przycisków
        play_state = "normal" if PYGAME_AVAILABLE and line_selected and audio_dir_set and files_exist else "disabled"
        gen_state = "normal" if line_selected and audio_dir_set and project_loaded and lines_processed else "disabled"

        del_state = "normal" if line_selected and audio_dir_set and files_exist else "disabled"
        del_all_state = del_state

        edit_state = "normal" if line_selected and lines_processed else "disabled"

        self.play_button.configure(state=play_state)
        self.generate_button.configure(state=gen_state)
        self.delete_button.configure(state=del_state)
        self.delete_all_button.configure(state=del_all_state)
        # Ustaw stan nowego przycisku
        self.edit_line_button.configure(state=edit_state)

    def _get_selected_identifier(self) -> str | None:
        """Returns the identifier (line number as string) of the selected line, or None."""
        if self.selected_line_index is not None:
            return str(self.selected_line_index + 1)
        return None

    def _find_audio_files(self, identifier: str) -> List[Tuple[Path, bool]]:
        """Finds audio files for a given identifier."""
        if not self.audio_dir:
            return []
        # Uwzględniamy mp3 z elevenlabs
        candidates = [
            (self.audio_dir / f"output1 ({identifier}).wav", False),
            # Dodano mp3
            (self.audio_dir / f"output1 ({identifier}).mp3", False),
            (self.audio_dir / f"output1 ({identifier}).ogg", False),
            (self.audio_dir / "ready" / f"output1 ({identifier}).ogg", True),
            (self.audio_dir / "ready" / f"output2 ({identifier}).ogg", True)
        ]
        return [(f, ready) for f, ready in candidates if f.exists()]

    def stop_audio(self):
        """Stops and unloads any currently playing audio file."""
        if not PYGAME_AVAILABLE:
            return
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass

    def play_selected_audio(self, event=None):
        """Plays the first available audio file for the selected line."""
        if not PYGAME_AVAILABLE:
            return
        identifier = self._get_selected_identifier()
        if not identifier or not self.audio_dir:
            return

        files = self._find_audio_files(identifier)
        if files:
            selected_name = self.audio_select_var.get()
            file_to_play = next(
                (f for f, _ in files if f.name == selected_name), files[0][0])
            self.stop_audio()  # Zatrzymaj poprzedni
            try:
                print(f"Odtwarzam: {file_to_play}")
                pygame.mixer.music.load(str(file_to_play))
                pygame.mixer.music.play()
            except Exception as e:
                messagebox.showerror(
                    "Błąd odtwarzania", f"Nie udało się odtworzyć pliku:\n{e}", parent=self)
        else:
            messagebox.showinfo(
                "Brak pliku", "Brak plików audio dla tej linii.", parent=self)

    def delete_selected_audio(self):
        """Deletes the *first found* audio file for the selected line."""
        identifier = self._get_selected_identifier()
        if not identifier or not self.audio_dir:
            return

        files = self._find_audio_files(identifier)
        if not files:
            messagebox.showinfo(
                "Brak plików", "Brak plików audio do usunięcia dla tej linii.", parent=self)
            return
        selected_name = self.audio_select_var.get()
        file_to_delete = next(
            (f for f, _ in files if f.name == selected_name), files[0][0])
        self._delete_single_file_with_check(file_to_delete)

    def delete_all_selected_audio(self):
        """Deletes *all* found audio files for the selected line."""
        identifier = self._get_selected_identifier()
        if not identifier or not self.audio_dir:
            return

        files = self._find_audio_files(identifier)
        if not files:
            messagebox.showinfo(
                "Brak plików", "Brak plików audio do usunięcia dla tej linii.", parent=self)
            return

        # Sprawdź, czy którykolwiek plik jest odtwarzany
        if PYGAME_AVAILABLE:
            try:
                if pygame.mixer.music.get_busy():
                    # Sprawdź, czy odtwarzany plik jest jednym z tych do usunięcia
                    # (Pygame nie udostępnia ścieżki, więc musimy to pominąć - użytkownik musi zatrzymać)
                    messagebox.showwarning("Plik w użyciu",
                                           "Audio jest odtwarzane. Zatrzymaj je (np. klikając Play dla innej linii) przed usunięciem.",
                                           parent=self)
                    return
            except Exception:
                pass

        # Potwierdzenie
        file_list_str = "\n".join([f.name for f, rdy in files])
        if not messagebox.askyesno("Potwierdź usunięcie",
                                   f"Czy na pewno usunąć WSZYSTKIE ({len(files)}) pliki dla linii {identifier}?\n{file_list_str}",
                                   parent=self):
            return

        self.stop_audio()  # Zatrzymaj na wszelki wypadek

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

        self.update_audio_buttons_state()  # Odśwież stan przycisków

    def _delete_single_file_with_check(self, file_path: Path):
        """Internal helper to delete a single file with safety checks."""
        if PYGAME_AVAILABLE:
            try:
                if pygame.mixer.music.get_busy():
                    messagebox.showwarning("Plik w użyciu",
                                           "Nie można usunąć pliku podczas odtwarzania. Zatrzymaj je i spróbuj ponownie.",
                                           parent=self)
                    return
            except Exception:
                pass

        self.stop_audio()  # Zatrzymaj i zwolnij

        self.lift()
        self.focus_force()
        if os.path.exists(file_path) and messagebox.askyesno("Potwierdź", f"Usunąć plik?\n{file_path.name}",
                                                             parent=self):
            try:
                os.remove(file_path)
                self.update_audio_buttons_state()  # Odśwież stan przycisków
            except Exception as e:
                messagebox.showerror(
                    "Błąd", f"Nie udało się usunąć pliku:\n{e}", parent=self)

    def choose_audio_dir(self):
        """Opens dialog to choose audio directory."""
        init_dir = self.global_config.get('start_directory') or (
            str(self.audio_dir) if self.audio_dir else None)
        path = filedialog.askdirectory(
            title="Wybierz katalog audio", initialdir=init_dir, parent=self)
        if path:
            new_dir = Path(path)
            if self.audio_dir != new_dir:
                self.audio_dir = new_dir
                if self.current_project_path:
                    self.set_project_config(
                        'audio_path', str(new_dir.absolute()))
                self.update_audio_buttons_state()

    # ===============================
    # === GENERATION LOGIC (NOWE) ===
    # ===============================

    def show_generation_queue(self):
        """Otwiera (lub przenosi na wierzch) okno kolejki generowania."""
        if self.queue_window is None or not self.queue_window.winfo_exists():
            self.queue_window = GenerationQueueWindow(self)
            self.queue_window.lift()
        else:
            self.queue_window.lift()

    def on_queue_window_close(self):
        """Callback z okna kolejki, aby poinformować okno główne."""
        self.queue_window = None

    def _gather_tts_config(self) -> dict:
        """Zbiera wszystkie ustawienia globalne potrzebne modelom TTS."""
        project_xtts_path = self.project_config.get('xtts_voice_path')

        return {
            'local_api_url': self.global_config.get('local_api_url'),
            # Użyj ścieżki projektu, jeśli istnieje; w przeciwnym razie użyj globalnej
            'xtts_voice_path': project_xtts_path or self.global_config.get('xtts_voice_path'),
            'elevenlabs_api_key': self.global_config.get('elevenlabs_api_key'),
            'elevenlabs_voice_id': self.global_config.get('elevenlabs_voice_id'),
            'google_credentials_path': self.global_config.get('google_credentials_path'),
            'google_voice_name': self.global_config.get('google_voice_name'),
        }

    def _gather_converter_config(self) -> dict:
        """Zbiera ustawienia dla konwertera."""
        try:
            base_speed = float(
                self.project_config.get('base_audio_speed', 1.1))
        except ValueError:
            base_speed = 1.1

        try:
            default_workers = max(1, os.cpu_count() //
                                  2 if os.cpu_count() else 4)
            max_workers = int(self.global_config.get(
                'conversion_workers', default_workers))
        except (ValueError, TypeError):
            default_workers = max(1, os.cpu_count() //
                                  2 if os.cpu_count() else 4)
            max_workers = default_workers

        return {
            'base_audio_speed': base_speed,
            'ffmpeg_filters': self.global_config.get('ffmpeg_filters', {}),
            'conversion_workers': max_workers
        }

    def _prepare_job_dependencies(self) -> bool:
        """Sprawdza, czy wszystko jest gotowe do dodania zadania."""
        if not self.audio_dir or not self.audio_dir.is_dir():
            messagebox.showwarning(
                "Brak katalogu", "Najpierw wybierz katalog audio w menu 'Dialogi'.", parent=self)
            return False

        if not self.current_project_path:
            messagebox.showwarning(
                "Brak projektu", "Zapisz projekt przed dodaniem do kolejki.", parent=self)
            return False

        if not self.processed_replace:
            messagebox.showwarning(
                "Brak danych", "Najpierw przetwórz napisy przyciskiem 'Zastosuj'.", parent=self)
            return False

        return True

    def enqueue_generate_single(self):
        """Dodaje zadanie generowania dla pojedynczej linii do kolejki."""
        identifier = self._get_selected_identifier()
        if identifier is None:
            messagebox.showwarning(
                "Brak zaznaczenia", "Najpierw wybierz linię z podglądu.", parent=self)
            return

        if not self._prepare_job_dependencies():
            return

        try:
            line_index = int(identifier) - 1
            text = self.processed_replace[line_index]
            lines_to_gen = [(identifier, text)]
        except (IndexError, ValueError):
            messagebox.showerror(
                "Błąd", f"Nie można pobrać tekstu dla ID: {identifier}", parent=self)
            return

        tts_model_name = self._get_active_tts_model_name()
        if not tts_model_name:
            messagebox.showerror(
                "Błąd modelu", "Nie wybrano aktywnego modelu TTS w ustawieniach projektu.", parent=self)
            return

        job = GenerationJob(
            project_path=f"POJEDYNCZY ({identifier}) - {self.current_project_path.name}",
            audio_dir=self.audio_dir,
            lines_to_generate=lines_to_gen,
            tts_model_name=tts_model_name,
            tts_config=self._gather_tts_config(),
            converter_config=self._gather_converter_config()
        )

        GenerationManager.get_instance().add_job(job)
        self.set_status(f"Dodano zadanie (linia {identifier}) do kolejki.")

    def enqueue_generate_all(self):
        """Dodaje zadanie generowania dla wszystkich brakujących linii do kolejki."""
        if not self._prepare_job_dependencies():
            return

        tts_model_name = self._get_active_tts_model_name()
        if not tts_model_name:
            messagebox.showerror(
                "Błąd modelu", "Nie wybrano aktywnego modelu TTS w ustawieniach projektu.", parent=self)
            return

        # Znajdź brakujące pliki
        dialogs_to_generate = []
        for i, text in enumerate(self.processed_replace):
            identifier = str(i + 1)
            raw_wav = self.audio_dir / f"output1 ({identifier}).wav"
            raw_mp3 = self.audio_dir / f"output1 ({identifier}).mp3"
            ready_ogg1 = self.audio_dir / "ready" / \
                f"output1 ({identifier}).ogg"
            ready_ogg2 = self.audio_dir / "ready" / \
                f"output2 ({identifier}).ogg"
            if not (raw_wav.exists() or raw_mp3.exists() or ready_ogg1.exists() or ready_ogg2.exists()):
                dialogs_to_generate.append((identifier, text))

        if not dialogs_to_generate:
            messagebox.showinfo(
                "Brak zadań", "Wszystkie pliki audio wydają się być wygenerowane.", parent=self)
            return

        job = GenerationJob(
            project_path=self.current_project_path.name,
            audio_dir=self.audio_dir,
            lines_to_generate=dialogs_to_generate,
            tts_model_name=tts_model_name,
            tts_config=self._gather_tts_config(),
            converter_config=self._gather_converter_config()
        )

        GenerationManager.get_instance().add_job(job)
        self.show_generation_queue()
        self.set_status(
            f"Dodano zadanie ({len(dialogs_to_generate)} linii) do kolejki.")

    def enqueue_convert_all(self):
        """Dodaje zadanie samej konwersji do kolejki."""
        if not self.audio_dir or not self.audio_dir.is_dir():
            messagebox.showwarning(
                "Brak katalogu", "Najpierw wybierz katalog audio.", parent=self)
            return

        if not self.current_project_path:
            messagebox.showwarning(
                "Brak projektu", "Zapisz projekt przed dodaniem do kolejki.", parent=self)
            return

        job = ConversionJob(
            project_path=f"KONWERSJA - {self.current_project_path.name}",
            audio_dir=self.audio_dir,
            converter_config=self._gather_converter_config()
        )

        GenerationManager.get_instance().add_job(job)
        self.show_generation_queue()
        self.set_status("Dodano zadanie konwersji audio do kolejki.")

    def check_queue(self):
        """Periodically checks queue for GUI updates."""
        try:
            task = self.queue.get_nowait()
        except queue.Empty:
            pass
        else:
            task()
        self.after(100, self.check_queue)

    def export_patterns_to_csv(self):
        """Exports custom 'replace' patterns to CSV file."""
        if not self.custom_replace:
            messagebox.showinfo(
                "Brak wzorców", "Brak własnych wzorców do eksportu.", parent=self)
            return

        path = filedialog.asksaveasfilename(
            title="Zapisz wzorce jako CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=self._get_save_dir()
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                # *** ZMIANA: Użyj QUOTE_ALL, aby uniknąć problemów ze znakami cudzysłowu ***
                writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                for p in self.custom_replace:
                    writer.writerow(
                        [p.pattern, p.replace, int(p.case_sensitive)])
            messagebox.showinfo(
                "Eksport zakończony", f"Zapisano {len(self.custom_replace)} wzorców do:\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror(
                "Błąd eksportu", f"Nie udało się zapisać pliku:\n{e}", parent=self)

    def add_remove_pattern_from_selection(self, event=None):
        """
        Dodaje wzorzec WYCINAJĄCY na podstawie zaznaczonej linii w podglądzie.
        Używa re.escape() do stworzenia wzorca literalnego.
        """
        if self.selected_line_index is None:
            return  # Brak zaznaczenia

        try:
            line_text = self.processed_replace[self.selected_line_index]
            if not line_text.strip():
                self.set_status("Pominięto dodanie wzorca (linia jest pusta).")
                return

            # Wyeskejpowany pattern (traktuj tekst literalnie)
            escaped_pattern = re.escape(line_text)

            new_pattern = PatternItem(
                pattern=escaped_pattern, replace="", case_sensitive=True)

            # Sprawdź, czy już nie istnieje
            if any(p.pattern == new_pattern.pattern for p in self.custom_remove):
                self.set_status(
                    f"Wzorzec '{escaped_pattern[:30]}...' już istnieje.")
                return

            # Dodaj do listy i UI
            self.custom_remove.append(new_pattern)
            self.add_row(self.custom_remove_frame,
                         new_pattern, self.custom_remove)
            self.mark_as_unsaved()

            self.set_status(
                f"Dodano wzorzec wycinający: {escaped_pattern[:30]}...")

        except IndexError:
            self.set_status(
                "Błąd: Nie można pobrać tekstu dla zaznaczonej linii.")
        except Exception as e:
            self.set_status(f"Błąd dodawania wzorca: {e}")

    def add_replace_pattern_from_selection(self, event=None):
        """
        Otwiera okno dodawania wzorca PODMIENIAJĄCEGO na podstawie
        zaznaczonej linii w podglądzie (wywołane przez Ctrl+Click).
        """
        if self.selected_line_index is None:
            return  # Brak zaznaczenia

        try:
            line_text = self.processed_replace[self.selected_line_index].strip(
            )
            if not line_text:
                self.set_status("Pominięto (linia jest pusta).")
                return

            # Otwórz okno dodawania (nie edycji)
            win = PatternEditorWindow(
                self,
                pattern_type='replace',
                callback=self.handle_pattern_update,
                existing_pattern=None
            )

            # Wypełnij pola tekstem z linii
            win.ent_pattern.insert(0, line_text)
            win.ent_replace.insert(0, line_text)
            # Domyślnie ustaw wrażliwość na wielkość liter
            win.var_case_sensitive.set(True)

            self.set_status("Otwarto edytor wzorców z zaznaczonym tekstem.")

        except IndexError:
            self.set_status(
                "Błąd: Nie można pobrać tekstu dla zaznaczonej linii.")
        except Exception as e:
            self.set_status(f"Błąd otwierania edytora: {e}")

    def open_audio_rename_window(self):
        """Otwiera okno do masowej zmiany nazw plików audio."""
        if not self.audio_dir or not self.audio_dir.is_dir():
            messagebox.showwarning(
                "Brak katalogu",
                "Najpierw wybierz katalog audio (menu 'Dialogi').",
                parent=self
            )
            return

        win = AudioRenameWindow(self, self.audio_dir)
        win.grab_set()

    def _get_active_tts_model_name(self) -> str | None:
        """Gets the active TTS model name from project config."""
        proj_cfg = self._gather_project_config()
        return proj_cfg.get('active_tts_model')

    def delete_all_converted_audio(self):
        """Usuwa wszystkie pliki .ogg z podkatalogu /ready."""
        if not self.audio_dir or not self.audio_dir.is_dir():
            messagebox.showwarning(
                "Brak katalogu", "Najpierw wybierz katalog audio w menu 'Dialogi'.", parent=self)
            return

        ready_dir = self.audio_dir / "ready"
        if not ready_dir.is_dir():
            messagebox.showinfo(
                "Brak folderu", f"Katalog '/ready' nie istnieje w:\n{self.audio_dir}", parent=self)
            return

        if not messagebox.askyesno("Potwierdź usunięcie",
                                   f"Czy na pewno chcesz usunąć CAŁĄ zawartość folderu /ready?\n\n{ready_dir}\n\nSpowoduje to usunięcie wszystkich przekonwertowanych plików .ogg.",
                                   parent=self):
            return

        self.stop_audio()

        deleted_count = 0
        errors = []

        try:
            # Bezpieczniej jest usuwać tylko pliki .ogg
            for f in ready_dir.glob('*.ogg'):
                try:
                    os.remove(f)
                    deleted_count += 1
                except Exception as e:
                    errors.append(f"{f.name}: {e}")

            if errors:
                messagebox.showerror("Błędy podczas usuwania",
                                     f"Usunięto {deleted_count} plików, ale wystąpiły błędy:\n" + "\n".join(
                                         errors),
                                     parent=self)
            elif deleted_count == 0:
                messagebox.showinfo("Gotowe",
                                    f"Folder /ready był już pusty (nie znaleziono plików .ogg).",
                                    parent=self)
            else:
                messagebox.showinfo("Gotowe",
                                    f"Pomyślnie usunięto {deleted_count} plików .ogg z folderu /ready.",
                                    parent=self)

        except Exception as e:
            messagebox.showerror("Błąd krytyczny",
                                 f"Nie udało się przeszukać folderu /ready:\n{e}", parent=self)

        self.update_audio_buttons_state()

    def apply_theme_settings(self):
        """Ustawia tryb wyglądu i paletę kolorów CustomTkinter."""
        mode = self.global_config.get('appearance_mode', 'System')
        theme = self.global_config.get('color_theme', 'blue')

        try:
            ctk.set_appearance_mode(mode)
            ctk.set_default_color_theme(theme)
            print(f"Zastosowano motyw: {mode}, kolor: {theme}")
        except Exception as e:
            print(f"Błąd podczas ustawiania motywu: {e}")
            ctk.set_appearance_mode('System')
            ctk.set_default_color_theme('blue')

    def _check_for_updates(self):
        """Sprawdza najnowszą wersję na GitHubie w osobnym wątku."""
        if not PACKAGING_AVAILABLE:
            return

        API_URL = "https://api.github.com/repos/kpasek/subtitle-studio/releases/latest"
        try:
            # Użyj sesji z timeoutem
            session = requests.Session()
            response = session.get(API_URL, timeout=10)
            response.raise_for_status()

            data = response.json()
            latest_tag = data.get('tag_name')

            if not latest_tag:
                print("Nie znaleziono tag_name w odpowiedzi API GitHub.")
                return

            # Porównywanie wersji
            current_v = version.parse(self.APP_VERSION)
            latest_v = version.parse(latest_tag)

            if latest_v > current_v:
                print(
                    f"Znaleziono nową wersję: {latest_tag} (Bieżąca: {self.APP_VERSION})")

                # Ustalanie linku do pobierania
                download_url = None
                if sys.platform == "win32":
                    download_url = f"https://github.com/kpasek/subtitle-studio/releases/download/{latest_tag}/SubtitleStudioWindows.zip"
                elif sys.platform.startswith("linux"):
                    download_url = f"https://github.com/kpasek/subtitle-studio/releases/download/{latest_tag}/SubtitleStudioLinux.zip"
                else:
                    # Dla innych systemów (np. macOS) po prostu otwórz stronę releasów
                    download_url = data.get(
                        'html_url', "https://github.com/kpasek/subtitle-studio/releases")

                self.latest_version_info = (latest_tag, download_url)

                # Wyślij zadanie do głównego wątku (GUI)
                self.queue.put(self._show_update_button)

        except requests.exceptions.RequestException as e:
            print(
                f"Błąd podczas sprawdzania aktualizacji (prawdopodobnie brak internetu): {e}")
        except version.InvalidVersion:
            print(
                f"Błąd parsowania wersji: {self.APP_VERSION} lub {latest_tag}")
        except Exception as e:
            print(f"Nieoczekiwany błąd w _check_for_updates: {e}")

    def _show_update_button(self):
        """Wywoływane z kolejki GUI, aby pokazać przycisk aktualizacji."""
        if self.latest_version_info and self.update_button:
            version_name, download_url = self.latest_version_info
            self.update_button.configure(text=f"Nowa Wersja! ({version_name})")
            # Użyj .pack() aby go pokazać, zachowując kolejność
            self.update_button.pack(side="left", padx=5)
            # Przesuń lbl_filename na lewo od przycisków po prawej
            self.lbl_filename.pack_configure(side="left", anchor="w", padx=5)

    def _download_update(self):
        """Otwiera przeglądarkę z linkiem do pobrania nowej wersji."""
        if self.latest_version_info:
            version_name, download_url = self.latest_version_info
            print(f"Otwieram przeglądarkę z linkiem: {download_url}")
            try:
                webbrowser.open(download_url, new=2)
            except Exception as e:
                print(f"Nie udało się otworzyć przeglądarki: {e}")
                messagebox.showerror(
                    "Błąd", f"Nie udało się otworzyć linku:\n{download_url}", parent=self)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    app = SubtitleStudioApp()
    app.mainloop()
