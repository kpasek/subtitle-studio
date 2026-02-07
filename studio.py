import multiprocessing
import os.path
import customtkinter as ctk
import tkinter as tk
import re
import sys
import os
import shutil
import threading
import queue
import ctypes

from pathlib import Path
from typing import List, Optional, Tuple
from tkinter import filedialog, messagebox

# --- Importy z modułów aplikacji ---
from app.pattern_manager import PatternManagerWindow
from app.settings import SettingsWindow
from app.utils import resource_path, is_installed
from app.entity import Line, PatternItem
from app.subtitles import SubtitlePanel
from ui.menu import AppMenu

# Refaktoryzacja IO -> app.io
from app.io import load_subtitle_file, save_lines_to_file
from app.patterns import gather_active_patterns, get_patterns_signature, apply_patterns as patterns_apply

from audio.audio_renamer import AudioRenameWindow
from audio.pattern_editor import PatternEditorWindow
from audio.deleter import AudioDeleterWindow
from audio.generation_queue import GenerationQueueWindow
from ui.game_reader_export import GameReaderExportWindow
from ui.pattern_io import PatternIOWindow
from ui.names_manager import NamesManagerWindow

from importlib import util as _import_util

PACKAGING_AVAILABLE = _import_util.find_spec("packaging") is not None
if not PACKAGING_AVAILABLE:
    print("Ostrzeżenie: Biblioteka 'packaging' nie jest zainstalowana.")

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    home = Path.home()
    application_path = home / '.config'

APP_CONFIG = os.path.join(application_path, "subtitle-studio.json")

APP_TITLE = "Subtitle Studio"

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
    (PatternItem(r"[@#$^&*\(\)\{\}]+", " ", False), "Usuń znaki specjalne jak @#$"),
    (PatternItem(r"\s{2,}", " ", False), "Zamień białe znaki na spacje"),
    (PatternItem(r"^[-.\"\']", "", False), "Usuń wiodące znaki specjalne (-.\"')"),
    (PatternItem(r"[-\"\']$", "", False), "Usuń kończące znaki specjalne (-\"')"),
]

FFPLAY_AVAILABLE = shutil.which("ffplay") is not None
if not FFPLAY_AVAILABLE:
    print("Ostrzeżenie: Nie znaleziono 'ffplay' w zmiennych środowiskowych (PATH).")

if os.name == "nt":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class SubtitleStudioApp(ctk.CTk):
    """Główna klasa aplikacji Subtitle Studio."""
    APP_VERSION = "0.13.0"

    def __init__(self):
        super().__init__(className="SubtitleStudio")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.has_unsaved_changes = False
        self.global_config = {}

        self.title(APP_TITLE)
        self.geometry("1700x1000")
        try:
            self.iconphoto(False, tk.PhotoImage(
                file=resource_path("assets/icon512.png")))
        except Exception:
            pass

        self._load_app_config(only_config=True)

        self.loaded_path: Optional[Path] = None

        self.lines: List[Line] = []

        self.names_list: List[str] = []

        # Zmienne GUI i Cache (inicjalizacja)
        self.lbl_filename: Optional[ctk.CTkLabel] = None
        self._cache_clean_base: List[str] | None = None
        self._last_remove_signature = None
        self._cache_replace_result: List[str] | None = None
        self._last_replace_signature = None

        # Edycje
        self.manual_edits: dict[int, str] = {}
        self.tts_edits: dict[int, str] = {}

        last_view = self.global_config.get('last_view_mode', 'Napisy')
        self.view_mode = tk.StringVar(value=last_view)

        # Wzorce builtin
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
        self.torch_installed = is_installed('torch')

        self.queue = queue.Queue()
        self.queue_window: Optional[GenerationQueueWindow] = None
        self.pattern_manager_window: Optional[PatternManagerWindow] = None

        self.audio_dir: Optional[Path] = None
        self.selected_line_index: Optional[int] = None

        self.update_button: Optional[ctk.CTkButton] = None
        self.latest_version_info: Optional[Tuple[str, str]] = None

        self.apply_theme_settings()

        # Inicjalizacja Menu
        AppMenu(self).create()

        self._create_widgets()
        self._load_app_config()
        self.check_queue()

        self._bind_shortcuts()

        threading.Thread(target=self._check_for_updates, daemon=True).start()
                
        # Sprawdzamy, czy w konfiguracji jest zapisany ostatni projekt i czy plik istnieje
        last_proj = self.global_config.get('last_project')
        if last_proj and os.path.exists(last_proj):
            # Używamy 'after', aby pozwolić GUI na pełną inicjalizację przed wczytaniem ciężkiego projektu
            self.after(100, lambda: self.open_project(last_proj))
            self.subtitle_panel._on_filter_apply()

    def _bind_shortcuts(self):
        """Rejestruje globalne skróty klawiszowe."""
        # Nawigacja i Projekt
        self.bind("<Control-e>", lambda e: self.open_recent_projects_window())
        self.bind("<Control-s>", lambda e: self.save_project())
        self.bind("<Control-f>", lambda e: self.subtitle_panel.search_entry.focus_set())
        self.bind("<Control-q>", lambda e: self.show_generation_queue())
        self.bind("<Control-n>", lambda e: self._add_selected_text_to_names())
        self.bind("<Control-N>", lambda e: self.open_names_manager())

        self.bind("<Tab>", self._cycle_view_mode)
        self.bind("<Escape>", self._on_escape_key)

        # Audio i Wzorce
        self.bind("<Control-R>",
                  lambda e: self.enqueue_convert_all())  # Shift+Ctrl+r (Tkinter widzi Shift jako wielką literę)
        self.bind("<Control-r>", lambda e: self.open_pattern_manager())
        self.bind("<Control-G>", lambda e: self.enqueue_generate_all())  # Shift+Ctrl+g

        # Kontekstowe (Linia) - bindujemy do root, ale sprawdzamy kontekst w metodach
        self.bind("<Control-space>", lambda e: self.subtitle_panel.play_selected_audio())
        self.bind("<Control-g>", lambda e: self.enqueue_generate_single())

        # Ctrl+X (Usuń audio) - uwaga na konflikt z wycinaniem tekstu
        self.bind("<Control-x>", self._on_ctrl_x)
        self.bind("<Control-c>", self._on_ctrl_c)

        # Klawisz Delete (Usuń treść)
        # Bindujemy go tutaj globalnie, ale logika sprawdzi, czy nie jesteśmy w polu edycji
        self.bind("<Delete>", self._on_delete_key)

    def _cycle_view_mode(self, event=None):
        """Przełącza widok między Napisy a TTS (pomija Oryginał)."""
        current = self.view_mode.get()
        if current == "Napisy":
            self.subtitle_panel.view_switcher.set("TTS")
            self.view_mode.set("TTS")
        else:
            self.subtitle_panel.view_switcher.set("Napisy")
            self.view_mode.set("Napisy")

        # Wywołujemy metodę zmiany widoku w panelu
        self.subtitle_panel._on_view_mode_change("TTS" if current == "Napisy" else "Napisy")
        return "break"

    def _on_ctrl_c(self, event=None):
        """
        Obsługa Ctrl+C.
        Priorytet:
        1. Jeśli fokus jest na liście dialogów -> Kopiuj całą linię (wymuś).
        2. Jeśli fokus jest na innym polu edycji (Edytor, Szukaj) -> Systemowe kopiowanie.
        3. W innym przypadku -> Kopiuj całą linię.
        """
        widget = self.focus_get()

        # Sprawdź, czy fokus jest na liście dialogów (Treeview)
        is_preview_list = (widget == self.subtitle_panel.tree)

        if is_preview_list:
            # Wymuszamy kopiowanie linii, ignorując systemowe kopiowanie zaznaczenia
            self._on_ctrl_c_from_menu()
            return "break"  # Zatrzymaj propagację zdarzenia

        # Jeśli jesteśmy w normalnym polu edycji (np. search, line editor),
        # pozwalamy systemowi obsłużyć skrót (standardowe kopiowanie tekstu zaznaczonego myszką)
        if isinstance(widget, (tk.Entry, ctk.CTkEntry, ctk.CTkTextbox, tk.Text)):
            return

            # Fallback dla innych przypadków (np. fokus na ramce)
        self._on_ctrl_c_from_menu()

    def _on_ctrl_c_from_menu(self):
        """Faktyczna logika kopiowania wywoływana z menu kontekstowego lub Ctrl+C."""
        if self.selected_line_index is None:
            return

        idx = self.selected_line_index
        mode = self.view_mode.get()
        text_to_copy = ""

        try:
            # --- ZMIANA: Użycie self.lines zamiast osobnych list ---
            line = self.lines[idx]
            if mode == "Oryginał":
                text_to_copy = line.original_text
            elif mode == "Napisy":
                text_to_copy = line.text
            elif mode == "TTS":
                text_to_copy = line.tts_text
            # -------------------------------------------------------
        except IndexError:
            return

        if text_to_copy:
            self.clipboard_clear()
            self.clipboard_append(text_to_copy)
            self.set_status(f"Skopiowano linię {idx + 1} do schowka.")

    def _on_ctrl_x(self, event=None):
        """Obsługa Ctrl+X (Usuń audio), z zabezpieczeniem edycji tekstu."""
        # Jeśli fokus jest w polu tekstowym (Editor lub Search), pozwól na standardowe 'Wytnij'
        widget = self.focus_get()
        if isinstance(widget, (tk.Entry, ctk.CTkEntry, ctk.CTkTextbox, tk.Text)):
            return  # Nie blokuj zdarzenia, niech system zrobi "Cut"

        # W przeciwnym razie usuń audio
        self.subtitle_panel.delete_all_selected_audio()

    def _on_escape_key(self, event=None):
        """
        Obsługa klawisza ESC:
        1. Czyści wyszukiwarkę i odświeża listę.
        2. Usuwa zaznaczenie linii (jeśli istnieje) i czyści edytor.
        """
        # 1. Czyść wyszukiwarkę i nr linii
        self.subtitle_panel.search_entry.delete(0, tk.END)
        self.subtitle_panel.search_line_nr.delete(0, tk.END)
        self.apply_patterns()  # Odświeża listę dialogów

        # 2. Usuń zaznaczenie
        if self.selected_line_index is not None:
            self.selected_line_index = None
            try:
                self.subtitle_panel.tree.selection_set(())
            except Exception:
                pass
            self.set_status("Wyszukiwanie anulowane, linia odznaczona.")

        return "break"

    def _on_delete_key(self, event=None):
        """Obsługa Del (Wyczyść linię), z zabezpieczeniem edycji tekstu."""
        widget = self.focus_get()
        # Jeśli piszemy w edytorze lub wyszukiwarce, Del ma usuwać znaki
        if isinstance(widget, (tk.Entry, ctk.CTkEntry)):
            return

            # Jeśli nie edytujemy tekstu, czyścimy zawartość linii
        self._clear_selected_line_content()

    def _clear_selected_line_content(self):
        """Czyści treść aktualnie zaznaczonej linii (zastępuje pustym stringiem)."""
        if self.selected_line_index is None:
            return

        mode = self.view_mode.get()
        idx = self.selected_line_index

        # Nie pozwalamy edytować oryginału
        if mode == "Oryginał":
            messagebox.showinfo("Info", "Nie można edytować oryginału.", parent=self)
            return

        # Pusta wartość
        empty_val = ""

        # Zaktualizuj bezpośrednio w app.lines
        if mode == "Napisy":
            self.lines[idx].text = empty_val
        elif mode == "TTS":
            self.lines[idx].tts_text = empty_val
        
        # Zapisz do CSV
        try:
            from app.io import update_line_in_csv
            if self.loaded_path:
                update_line_in_csv(str(self.loaded_path), idx, self.lines[idx])
        except Exception as e:
            print(f"Błąd zapisu do CSV: {e}")

        self.apply_patterns()
        self.subtitle_panel.set_preview(self.lines)
        self.set_status(f"Wyczyszczono zawartość linii {idx + 1}")

    def open_shortcuts_window(self):
        from app.ui_helpers import open_shortcuts_window as _open_shortcuts_window
        return _open_shortcuts_window(self)

    def mark_as_unsaved(self, *args):
        """Oznacza projekt jako niezapisany."""
        if self.current_project_path:
            self.has_unsaved_changes = True
            if "Gotowy" in self.status.cget("text") and "niezapisane" not in self.status.cget("text"):
                self.set_status(f"{self.status.cget('text')} (niezapisane zmiany)")

    def _create_widgets(self):
        """Tworzy główny układ okna (Panel napisów + Status)."""
        root_grid = ctk.CTkFrame(self)
        root_grid.pack(fill="both", expand=True, padx=10, pady=10)
        root_grid.grid_rowconfigure(0, weight=1)
        root_grid.grid_columnconfigure(0, weight=1)

        # --- Subtitle Panel (Prawa strona / Główny widok) ---
        self.subtitle_panel = SubtitlePanel(root_grid, app=self)
        self.subtitle_panel.grid(row=0, column=0, sticky="nsew")

        # --- Status Bar & Statistics (Dół) ---
        bottom_bar = ctk.CTkFrame(self, fg_color="transparent")
        bottom_bar.pack(fill="x", side="bottom", padx=10, pady=(0, 5))

        self.status = ctk.CTkLabel(bottom_bar, text="Gotowy", anchor="w")
        self.status.pack(side="left", padx=5)

        self.lbl_count_orig = ctk.CTkLabel(bottom_bar, text="Linie org.: 0")
        self.lbl_count_orig.pack(side="right", padx=10)

        self.lbl_count_after = ctk.CTkLabel(bottom_bar, text="Linie po: 0")
        self.lbl_count_after.pack(side="right", padx=10)

        self.lbl_count_words = ctk.CTkLabel(bottom_bar, text="Słowa: 0")
        self.lbl_count_words.pack(side="right", padx=10)

        self.lbl_count_chars = ctk.CTkLabel(bottom_bar, text="Znaki: 0")
        self.lbl_count_chars.pack(side="right", padx=10)

    # --- PATTERN MANAGEMENT ---
    def open_pattern_manager(self):
        if self.pattern_manager_window is None or not self.pattern_manager_window.winfo_exists():
            self.pattern_manager_window = PatternManagerWindow(self)
            # Podpinamy się pod zdarzenie zamknięcia okna "krzyżykiem"
            self.pattern_manager_window.protocol("WM_DELETE_WINDOW", self._on_pattern_manager_close)
        else:
            self.pattern_manager_window.lift()

    def _on_pattern_manager_close(self):
        """Obsługa zamknięcia menedżera wzorców - odświeżenie widoku."""
        if self.pattern_manager_window:
            self.pattern_manager_window.destroy()
            self.pattern_manager_window = None
        # Odśwież widok (przelicz ponownie wzorce i zaktualizuj listę)
        self.apply_patterns()

    def build_clean_list_frame(self, parent_frame, row_nr) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent_frame)
        frame.grid(row=row_nr, column=0, sticky="ew", pady=(4, 4))
        return frame

    def build_scroll_list_frame(self, parent_frame, row_nr) -> ctk.CTkScrollableFrame:
        frame = ctk.CTkScrollableFrame(parent_frame)
        frame.grid(row=row_nr, column=0, sticky="nsew", padx=6, pady=(2, 6))
        return frame

    def _create_builtin_list(self, parent, patterns, states, row_nr):
        sc = ctk.CTkScrollableFrame(parent)
        sc.grid(row=row_nr, column=0, sticky="nsew", padx=6, pady=(0, 6))
        for i, p in enumerate(patterns):
            text = f"{p.pattern} -> {p.replace}" if p.name is None else p.name
            cb = ctk.CTkCheckBox(sc, text=text, variable=states[i])
            cb.pack(anchor="w", pady=2)

    def open_add_remove_pattern(self):
        PatternEditorWindow(self, pattern_type='remove', callback=self.handle_pattern_update, existing_pattern=None)

    def open_add_replace_pattern(self):
        PatternEditorWindow(self, pattern_type='replace', callback=self.handle_pattern_update, existing_pattern=None)

    def open_edit_pattern(self, pattern: PatternItem, target_list: List[PatternItem]):
        pattern_type = 'remove' if target_list is self.custom_remove else 'replace'
        PatternEditorWindow(self, pattern_type=pattern_type, callback=self.handle_pattern_update,
                            existing_pattern=pattern)

    def handle_pattern_update(self, new_pattern: PatternItem, old_pattern: Optional[PatternItem], pattern_type: str):
        target_list = self.custom_remove if pattern_type == 'remove' else self.custom_replace
        if old_pattern:
            try:
                index = target_list.index(old_pattern)
                target_list[index] = new_pattern
            except ValueError:
                target_list.append(new_pattern)
        else:
            target_list.append(new_pattern)
        self.mark_as_unsaved()
        self.set_status("Zaktualizowano wzorce.")
        self._refresh_custom_lists()

    def add_row(self, frame, pattern_item: PatternItem, target_list: List[PatternItem]):
        pass

    def _refresh_custom_lists(self):
        if self.pattern_manager_window and self.pattern_manager_window.winfo_exists():
            self.pattern_manager_window.refresh_ui()

    # --- PROCES PRZETWARZANIA ---

    def _gather_active_patterns(self) -> tuple[List[PatternItem], List[PatternItem]]:
        """Deleguje zbieranie aktywnych wzorców do app.patterns.gather_active_patterns."""
        return gather_active_patterns(self.custom_remove, self.custom_replace)

    def _get_patterns_signature(self, patterns: List[PatternItem]):
        """Deleguje tworzenie sygnatury wzorców do app.patterns.get_patterns_signature."""
        return get_patterns_signature(patterns)

    def apply_patterns(self, force_refresh=False):
        """Deleguje aplikowanie wzorców do `app.patterns.apply_patterns`."""
        patterns_apply(self, force_refresh=force_refresh)

    def _update_subtitle_panel_content(self):
        """Pomocnicza metoda do odświeżania panelu w zależności od trybu."""
        mode = self.view_mode.get()
        display_list = []
        
        if mode == "Oryginał":
            display_list = [l.original_text for l in self.lines]
        elif mode == "Napisy":
            display_list = [l.text for l in self.lines]
        elif mode == "TTS":
            display_list = [l.tts_text for l in self.lines]

        # Statystyki
        total_words = sum(len(line.split()) for line in display_list)
        total_chars = sum(len(line) for line in display_list)

        self.lbl_count_after.configure(text=f'Linie po: {len(self.lines):,}'.replace(",", " "))
        self.lbl_count_words.configure(text=f'Słowa: {total_words:,}'.replace(",", " "))
        self.lbl_count_chars.configure(text=f'Znaki: {total_chars:,}'.replace(",", " "))
        # pass Line objects instead of strings
        self.subtitle_panel.set_preview(self.lines)
        self.subtitle_panel.update_audio_buttons_state()


    def apply_processing(self):
        from app.patterns import apply_processing as _apply_processing
        return _apply_processing(self)

    def _finalize_processing(self, remove_empty: bool, remove_duplicates: bool):
        from app.patterns import _finalize_processing as _finalize_processing_impl
        return _finalize_processing_impl(self, remove_empty, remove_duplicates)


    # --- GENEROWANIE ---

    def _prepare_job_dependencies(self) -> bool:
        from app.generation import prepare_job_dependencies
        return prepare_job_dependencies(self)

    def enqueue_generate_single(self, line_no = None):
        from app.generation import enqueue_generate_single as _enqueue_generate_single
        return _enqueue_generate_single(self, line_no)

    def enqueue_generate_all(self):
        from app.generation import enqueue_generate_all as _enqueue_generate_all
        return _enqueue_generate_all(self)

    def _execute_generate_all(self, overwrite: bool):
        from app.generation import _execute_generate_all as _execute_generate_all_impl
        return _execute_generate_all_impl(self, overwrite)

    def enqueue_convert_all(self):
        from app.generation import enqueue_convert_all as _enqueue_convert_all
        return _enqueue_convert_all(self)

    def _execute_convert_all(self, overwrite: bool):
        from app.generation import _execute_convert_all as _execute_convert_all_impl
        return _execute_convert_all_impl(self, overwrite)

    # --- PROJECT / SETTINGS / HELPERS ---

    def open_project(self, path: str | None = None):
        from app.project import open_project as _open_project
        return _open_project(self, path)

    def close_project(self):
        from app.project import close_project as _close_project
        return _close_project(self)

    def save_project(self, cfg: dict | None = None):
        from app.project import save_project as _save_project
        return _save_project(self, cfg)

    def save_project_as(self):
        from app.project import save_project_as as _save_project_as
        return _save_project_as(self)

    def set_project_config(self, param, value):
        from app.project import set_project_config as _set_project_config
        return _set_project_config(self, param, value)

    def _gather_project_config(self) -> dict:
        from app.project import _gather_project_config as _gather_project_config_impl
        return _gather_project_config_impl(self)

    def _load_app_config(self, only_config=False):
        from app.project import _load_app_config as _load_app_config_impl
        return _load_app_config_impl(self, only_config=only_config)

    def save_app_setting(self, param, value):
        from app.project import save_app_setting as _save_app_setting
        return _save_app_setting(self, param, value)

    def save_global_config(self, data: dict):
        from app.project import save_global_config as _save_global_config
        return _save_global_config(self, data)

    def _check_unsaved_changes(self) -> bool:
        from app.project import _check_unsaved_changes as _check_unsaved_changes_impl
        return _check_unsaved_changes_impl(self)

    def on_close(self):
        if self._check_unsaved_changes():
            if hasattr(self, 'subtitle_panel'):
                self.subtitle_panel.stop_audio()
            self.quit()

    def check_queue(self):
        try:
            task = self.queue.get_nowait()
            task()
        except queue.Empty:
            pass

        # Sprawdź audio w panelu
        if hasattr(self, 'subtitle_panel') and self.subtitle_panel.current_audio_process:
            if self.subtitle_panel.current_audio_process.poll() is not None:
                self.subtitle_panel.current_audio_process = None

        self.after(100, self.check_queue)

    # --- INNE POMOCNICZE ---
    def _get_save_dir(self):
        return self.global_config.get('start_directory')

    def set_status(self, txt):
        self.status.configure(text=txt)

    def _get_active_tts_model_name(self):
        return self.project_config.get('active_tts_model')

    def _gather_tts_config(self):
        return {
            'local_api_url': self.global_config.get('local_api_url', 'http://127.0.0.1:8001'),
            'xtts_voice_path': self.project_config.get('xtts_voice_path') or self.global_config.get('xtts_voice_path'),
            'piper_model_path': self.project_config.get('piper_model_path') or self.global_config.get('piper_model_path'),
            'elevenlabs_api_key': self.global_config.get('elevenlabs_api_key'),
            'elevenlabs_voice_id': self.global_config.get('elevenlabs_voice_id'),
            'google_credentials_path': self.global_config.get('google_credentials_path'),
            'google_voice_name': self.global_config.get('google_voice_name'),
        }

    def _gather_converter_config(self):
        default_workers = max(1, os.cpu_count() // 2 if os.cpu_count() else 4)
        max_workers = int(self.global_config.get('conversion_workers', default_workers))
        return {
            'ffmpeg_filters': self.global_config.get('ffmpeg_filters', {}),
            'conversion_workers': max_workers,
            'audio_output_format': self.global_config.get('audio_output_format', 'ogg')
        }

    def show_generation_queue(self):
        if self.queue_window is None or not self.queue_window.winfo_exists():
            self.queue_window = GenerationQueueWindow(self)
        self.queue_window.lift()

    def add_remove_pattern_from_selection(self, event=None):
        """Dodaje wzorzec wycinający (wywołane z panelu)."""
        if self.selected_line_index is None: return
        try:
            text = self.lines[self.selected_line_index].tts_text
            escaped = re.escape(text)
            if any(p.pattern == escaped for p in self.custom_remove): return
            self.custom_remove.append(PatternItem(escaped, "", True))
            self.mark_as_unsaved()
            self._refresh_custom_lists()
            self.set_status("Dodano wzorzec wycinający.")
        except IndexError:
            pass

    def add_replace_pattern_from_selection(self, event=None, from_menu=False):
        if self.selected_line_index is None: return
        try:
            text = self.lines[self.selected_line_index].tts_text.strip()
            if not text: return
            win = PatternEditorWindow(self, 'replace', self.handle_pattern_update, None)
            win.ent_pattern.insert(0, text)
            win.ent_replace.insert(0, text)
            win.var_case_sensitive.set(True)
            if from_menu: win.lift()
        except IndexError:
            pass

    def _check_for_updates(self):
        from app.update import check_for_updates as _check_for_updates_impl
        return _check_for_updates_impl(self)

    def _show_update_button(self):
        from app.update import show_update_button as _show_update_button_impl
        return _show_update_button_impl(self)

    def _download_update(self):
        from app.update import download_update as _download_update_impl
        return _download_update_impl(self)

    def show_about_window(self):
        from app.ui_helpers import show_about_window as _show_about_window
        return _show_about_window(self)

    # Proxy dla metod z menu
    def open_audio_deleter(self):
        if not self.lines: return messagebox.showwarning("Brak danych", "Najpierw przetwórz.", parent=self)
        if not self.audio_dir: return messagebox.showwarning("Brak katalogu", "Ustaw katalog audio.", parent=self)

        AudioDeleterWindow(self, self.lines, str(self.audio_dir)).wait_visibility().grab_set()

    def open_global_settings(self):
        SettingsWindow(self, self.torch_installed, mode='global').wait_visibility().grab_set()

    def open_project_settings(self):
        if not self.current_project_path: return messagebox.showwarning("Brak projektu", "Zapisz projekt.", parent=self)
        SettingsWindow(self, self.torch_installed, mode='project').wait_visibility().grab_set()

    def choose_audio_dir(self):
        init_dir = self.global_config.get('start_directory') or (str(self.audio_dir) if self.audio_dir else None)
        path = filedialog.askdirectory(title="Wybierz katalog audio", initialdir=init_dir, parent=self)
        if path:
            self.audio_dir = Path(path)
            if self.current_project_path: self.set_project_config('audio_path', str(self.audio_dir.absolute()))
            self.subtitle_panel.update_audio_buttons_state()

    def open_audio_rename_window(self, target_id=None, source_id=None):
        """Otwiera okno ręcznego dopasowywania/przesuwania plików audio."""
        if not self.audio_dir:
            messagebox.showwarning("Brak audio", "Nie wybrano katalogu audio.")
            return
            # Przekazujemy parametry do okna
        AudioRenameWindow(self, self.audio_dir, initial_target=target_id, initial_source=source_id)

    def delete_all_converted_audio(self):
        if not self.audio_dir: return messagebox.showwarning("Brak katalogu", "Wybierz katalog audio.", parent=self)
        ready_dir = self.audio_dir / "ready"
        if not ready_dir.is_dir() or not messagebox.askyesno("Potwierdź", f"Usunąć wszystko z {ready_dir}?"): return

        # POPRAWKA: Uwzględnienie zarówno plików .ogg jak i .mp3
        files_to_delete = list(ready_dir.glob('*.ogg')) + list(ready_dir.glob('*.mp3'))

        for f in files_to_delete:
            try:
                os.remove(f)
            except:
                pass
        self.subtitle_panel.update_audio_buttons_state()

    def download_clean(self):
        if not self.lines: return
        path = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('CSV', '*.csv'), ('Text files', '*.txt')])
        if path:
            if Path(path).suffix.lower() == '.csv':
                save_lines_to_file(path, self.lines)
            else:
                save_lines_to_file(path, [l.text for l in self.lines])
            messagebox.showinfo('Gotowe', f'Zapisano: {path}')

    def download_replace(self):
        if not self.lines: return
        path = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('CSV', '*.csv'), ('Text files', '*.txt')])
        if path:
            if Path(path).suffix.lower() == '.csv':
                save_lines_to_file(path, self.lines)
            else:
                save_lines_to_file(path, [l.tts_text for l in self.lines])
            messagebox.showinfo('Gotowe', f'Zapisano: {path}')

    def add_new_subtitles(self):
        """Dodaje nowe wiersze do pliku CSV z napisami. Jeśli plik nie istnieje, tworzy nowy."""
        from tkinter import simpledialog
        
        # Jeśli nie ma załadowanego pliku, pytamy użytkownika gdzie go stworzyć
        if not self.loaded_path:
            init_dir = self.global_config.get('start_directory')
            path = filedialog.asksaveasfilename(
                title="Utwórz nowy plik CSV z napisami",
                defaultextension='.csv',
                filetypes=[('CSV', '*.csv')],
                initialdir=init_dir,
                parent=self
            )
            
            if not path:
                return
            
            self.loaded_path = Path(path)
            if self.lbl_filename:
                self.lbl_filename.configure(text=f"Plik: {self.loaded_path.name}")
        
        # Dialog z pytaniem ile wierszy dodać
        num_rows = simpledialog.askinteger(
            "Dodaj napisy",
            "Ile nowych wierszy dodać?",
            parent=self,
            minvalue=1,
            maxvalue=1000,
            initialvalue=10
        )
        
        if num_rows is None or num_rows <= 0:
            return
        
        # Dodaj nowe wiersze do self.lines
        try:
            for _ in range(num_rows):
                new_line = Line(
                    original_text="",
                    text="",
                    tts_text="",
                    audio_duration=0.0,
                    audio_filename="",
                    audio_similarity=0.0,
                    audio_transcribed_text="",
                    audio_status="",
                    audio_format=""
                )
                self.lines.append(new_line)
            
            # Zapisz do CSV
            save_lines_to_file(str(self.loaded_path), self.lines)
            
            # Odświeź UI
            self.apply_patterns()
            
            self.set_status(f"Dodano {num_rows} nowych wierszy do {self.loaded_path.name}")
            messagebox.showinfo('Gotowe', f'Dodano {num_rows} nowych wierszy do pliku CSV.')
        except Exception as e:
            messagebox.showerror('Błąd', f'Nie udało się dodać wierszy: {str(e)}', parent=self)

    def change_subtitle_file(self):
        """Zmienia plik CSV z napisami na inny."""
        init_dir = self.global_config.get('start_directory')
        path = filedialog.askopenfilename(
            title="Wybierz plik CSV z napisami",
            filetypes=[('CSV', '*.csv'), ('Wszystkie pliki', '*.*')],
            initialdir=init_dir,
            parent=self
        )
        
        if not path:
            return
        
        # Sprawdzenie czy plik istnieje
        csv_path = Path(path)
        if not csv_path.exists():
            messagebox.showerror('Błąd', 'Wybrany plik nie istnieje.', parent=self)
            return
        
        try:
            # Wczytaj nowy plik
            self.lines = load_subtitle_file(str(csv_path))
            self.loaded_path = csv_path
            
            # Zaktualizuj etykietę z nazwą pliku
            if self.lbl_filename:
                self.lbl_filename.configure(text=f"Plik: {csv_path.name}")
            
            # Odśwież UI
            self.apply_patterns()
            
            self.set_status(f"Wczytano: {csv_path.name}")
            messagebox.showinfo('Gotowe', f'Wczytano plik: {csv_path.name}')
        except Exception as e:
            messagebox.showerror('Błąd', f'Nie udało się wczytać pliku: {str(e)}', parent=self)

    def generate_game_reader_preset(self):
        """Otwiera okno konfiguracji eksportu do Game Readera."""
        if not self.lines:
            messagebox.showwarning('Brak danych', 'Brak przetworzonych napisów do wyeksportowania.', parent=self)
            return

        if not self.audio_dir:
            messagebox.showwarning('Brak audio', 'Nie wybrano katalogu audio w projekcie.', parent=self)
            return

        # Otwórz nowe okno konfiguracji
        GameReaderExportWindow(self)

    def add_new_subtitles(self):
        """Dodaje nowe wiersze do pliku CSV. Może załadować z istniejącego CSV lub pliku TXT."""
        import datetime
        
        # Pytanie czy załadować z CSV czy TXT
        choice = messagebox.askyesno(
            "Dodaj napisy",
            "Czy załadować z pliku?\n\nTAK  - wybierz plik CSV lub TXT\nNIE - dodaj puste wiersze",
            parent=self
        )
        
        new_lines_to_add = []
        
        if choice:
            # Użytkownik wybrał załadowanie z pliku
            init_dir = self.global_config.get('start_directory')
            file_path = filedialog.askopenfilename(
                title="Wybierz plik CSV lub TXT z napisami",
                filetypes=[('CSV files', '*.csv'), ('Text files', '*.txt'), ('All files', '*.*')],
                initialdir=init_dir,
                parent=self
            )
            
            if not file_path:
                return
            
            file_path = Path(file_path)
            
            # Wczytaj plik w zależności od rozszerzenia
            try:
                if file_path.suffix.lower() == '.csv':
                    # Załaduj CSV
                    from app.io import load_subtitle_file
                    new_lines_to_add = load_subtitle_file(str(file_path))
                else:
                    # Załaduj TXT - każda linia jako original_text
                    with open(file_path, 'r', encoding='utf-8') as f:
                        lines_text = f.readlines()
                    
                    for line_text in lines_text:
                        line_text = line_text.rstrip('\n\r')
                        if line_text:  # Pomijaj puste linie
                            new_line = Line(
                                original_text=line_text,
                                text="",
                                tts_text="",
                                audio_duration=0.0,
                                audio_filename="",
                                audio_similarity=0.0,
                                audio_transcribed_text="",
                                audio_status="",
                                audio_format=""
                            )
                            new_lines_to_add.append(new_line)
                
                if not new_lines_to_add:
                    messagebox.showwarning('Brak danych', 'Plik nie zawiera żadnych danych.', parent=self)
                    return
                
            except Exception as e:
                messagebox.showerror('Błąd', f'Nie udało się wczytać pliku: {str(e)}', parent=self)
                return
        else:
            # Użytkownik wybrał dodanie ręczne
            from tkinter import simpledialog
            num_rows = simpledialog.askinteger(
                "Dodaj napisy",
                "Ile nowych wierszy dodać?",
                parent=self,
                minvalue=1,
                maxvalue=1000,
                initialvalue=10
            )
            
            if num_rows is None or num_rows <= 0:
                return
            
            # Utwórz puste wiersze
            for _ in range(num_rows):
                new_line = Line(
                    original_text="",
                    text="",
                    tts_text="",
                    audio_duration=0.0,
                    audio_filename="",
                    audio_similarity=0.0,
                    audio_transcribed_text="",
                    audio_status="",
                    audio_format=""
                )
                new_lines_to_add.append(new_line)
        
        # Automatycznie stwórz nowy plik CSV jeśli go nie ma
        if not self.loaded_path:
            try:
                # Określ katalog docelowy
                if self.current_project_path:
                    target_dir = self.current_project_path.parent / 'subtitles'
                    target_dir.mkdir(parents=True, exist_ok=True)
                else:
                    start_dir = self.global_config.get('start_directory')
                    target_dir = Path(start_dir) if start_dir else Path.home()
                
                # Utwórz nazwę pliku z timestampem
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                new_csv_filename = f"{timestamp}_subtitles.csv"
                self.loaded_path = target_dir / new_csv_filename
                
                if self.lbl_filename:
                    self.lbl_filename.configure(text=f"Plik: {self.loaded_path.name}")
                
            except Exception as e:
                messagebox.showerror('Błąd', f'Nie udało się utworzyć ścieżki pliku CSV: {str(e)}', parent=self)
                return
        
        # Dodaj nowe wiersze do self.lines i zapisz
        try:
            self.lines.extend(new_lines_to_add)
            
            # Zapisz do CSV
            save_lines_to_file(str(self.loaded_path), self.lines)
            
            # Odświeź UI
            self.apply_patterns()
            
            num_added = len(new_lines_to_add)
            self.set_status(f"Dodano {num_added} wierszy do {self.loaded_path.name}")
            messagebox.showinfo('Gotowe', f'Dodano {num_added} wierszy do pliku CSV.')
        except Exception as e:
            messagebox.showerror('Błąd', f'Nie udało się dodać wierszy: {str(e)}', parent=self)

    def change_subtitle_file(self):
        """Zmienia plik CSV z napisami na inny."""
        init_dir = self.global_config.get('start_directory')
        path = filedialog.askopenfilename(
            title="Wybierz plik CSV z napisami",
            filetypes=[('CSV', '*.csv'), ('Wszystkie pliki', '*.*')],
            initialdir=init_dir,
            parent=self
        )
        
        if not path:
            return
        
        # Sprawdzenie czy plik istnieje
        csv_path = Path(path)
        if not csv_path.exists():
            messagebox.showerror('Błąd', 'Wybrany plik nie istnieje.', parent=self)
            return
        
        try:
            # Wczytaj nowy plik
            self.lines = load_subtitle_file(str(csv_path))
            self.loaded_path = csv_path
            
            # Zaktualizuj etykietę z nazwą pliku
            if self.lbl_filename:
                self.lbl_filename.configure(text=f"Plik: {csv_path.name}")
            
            # Odśwież UI
            self.apply_patterns()
            
            self.set_status(f"Wczytano: {csv_path.name}")
            messagebox.showinfo('Gotowe', f'Wczytano plik: {csv_path.name}')
        except Exception as e:
            messagebox.showerror('Błąd', f'Nie udało się wczytać pliku: {str(e)}', parent=self)

    def import_patterns_from_csv(self):
        """Otwiera okno IO wzorców na zakładce Import."""
        win = PatternIOWindow(self)
        win.tabview.set("Import")

    def export_patterns_to_csv(self):
        """Otwiera okno IO wzorców na zakładce Eksport."""
        win = PatternIOWindow(self)
        win.tabview.set("Eksport")

    def apply_theme_settings(self):
        ctk.set_appearance_mode(self.global_config.get('appearance_mode', 'System'))
        ctk.set_default_color_theme(self.global_config.get('color_theme', 'blue'))

    def _update_recent_projects(self, path: str):
        from app.project import _update_recent_projects as _update_recent_projects_impl
        return _update_recent_projects_impl(self, path)

    def open_recent_projects_window(self):
        from app.project import open_recent_projects_window as _open_recent_projects_window
        return _open_recent_projects_window(self)

    def _remove_recent_project(self, path: str):
        from app.project import _remove_recent_project as _remove_recent_project_impl
        return _remove_recent_project_impl(self, path)

    def _clear_recent_projects(self):
        from app.project import _clear_recent_projects as _clear_recent_projects_impl
        return _clear_recent_projects_impl(self)

    def open_names_manager(self):
        """Otwiera okno zarządzania imionami."""
        NamesManagerWindow(self)

    def _show_editor_context_menu(self, event):
        from app.ui_helpers import show_editor_context_menu as _show_editor_context_menu
        return _show_editor_context_menu(self, event)

    def _add_selected_text_to_names(self):
        from app.ui_helpers import add_selected_text_to_names as _add_selected_text_to_names
        return _add_selected_text_to_names(self)

    # --- Proxy methods for integrated verification menu ---
    def start_verification(self):
        try:
            self.subtitle_panel.start_verification()
        except Exception as e:
            messagebox.showerror("Błąd", str(e), parent=self)

    def stop_verification(self):
        try:
            self.subtitle_panel.stop_verification()
        except Exception as e:
            messagebox.showerror("Błąd", str(e), parent=self)

    def refresh_verification(self):
        try:
            self.subtitle_panel._refresh_verification_view()
        except Exception as e:
            messagebox.showerror("Błąd", str(e), parent=self)

    def delete_all_bad_audio_verification(self):
        try:
            self.subtitle_panel.delete_all_bad_audio_verification()
        except Exception as e:
            messagebox.showerror("Błąd", str(e), parent=self)

    def open_verification_folder(self):
        try:
            self.subtitle_panel.open_verification_folder()
        except Exception as e:
            messagebox.showerror("Błąd", str(e), parent=self)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    app = SubtitleStudioApp()
    app.mainloop()
