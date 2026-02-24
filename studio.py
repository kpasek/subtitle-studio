import multiprocessing
import os.path
import customtkinter as ctk
import tkinter as tk
import sys
import os
import shutil
import threading
import queue
import ctypes

from pathlib import Path
from typing import List, Optional, Tuple
from tkinter import messagebox

# --- Importy z modułów aplikacji ---
from app.pattern_manager import PatternManagerWindow
from app.utils import resource_path, is_installed
from app.entity import Line, PatternItem
from app.subtitles import SubtitlePanel
from app.worker import Worker
from ui.menu import AppMenu

# Refaktoryzacja IO -> app.io
from app.io import set_project_path_provider

from app.patterns import (apply_patterns as patterns_apply, BUILTIN_REMOVE, BUILTIN_REPLACE, 
                          open_pattern_manager,
                          open_add_remove_pattern, open_add_replace_pattern, open_edit_pattern,
                          handle_pattern_update, add_remove_pattern_from_selection,
                          add_replace_pattern_from_selection, _clear_custom_list)
from app.project import (open_project, save_project, set_project_config, _load_app_config, 
                         save_app_setting, save_global_config, _check_unsaved_changes, 
                         open_recent_projects_window, 
                         gather_tts_config as _gather_tts_config,
                         gather_converter_config as _gather_converter_config)
from app.generation import (enqueue_generate_all, enqueue_convert_all)
from app.update import check_for_updates

from ui.verification_window import VerificationWindow
from ui.ai_runner import AITaskRunnerWindow

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


LineList = List[Line]


class SubtitleStudioApp(ctk.CTk):
    """Główna klasa aplikacji Subtitle Studio."""
    APP_TITLE = "Subtitle Studio"
    APP_VERSION = "0.15.0"

    def __init__(self):
        super().__init__(className="SubtitleStudio")
        
        set_project_path_provider(lambda: str(self.loaded_path) if self.loaded_path else None)

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

        _load_app_config(self)

        self.loaded_path: Optional[Path] = None
        self.lines: LineList = []

        self.lbl_filename: Optional[ctk.CTkLabel] = None
        self._cache_clean_base: List[str] | None = None
        self._last_remove_signature = None
        self._cache_replace_result: List[str] | None = None
        self._last_replace_signature = None

        self.manual_edits: dict[int, str] = {}
        self.tts_edits: dict[int, str] = {}

        last_view = self.global_config.get('last_view_mode', 'Napisy')
        self.view_mode = tk.StringVar(value=last_view)

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

        self.worker = Worker(name="StudioWorker", num_threads=2)
        # Przechowywanie stanu zadania AI w celu przywrócenia okna
        self.ai_state = None 

        self.queue = queue.Queue()

        self.pattern_manager_window: Optional[PatternManagerWindow] = None

        self.audio_dir: Optional[Path] = None
        self.selected_line_index: Optional[int] = None

        self.update_button: Optional[ctk.CTkButton] = None
        self.latest_version_info: Optional[Tuple[str, str]] = None

        self.apply_theme_settings()

        AppMenu(self).create()

        self._create_widgets()
        self.check_queue()
        self._bind_shortcuts()

        threading.Thread(target=lambda: check_for_updates(self), daemon=True).start()
                
        last_proj = self.global_config.get('last_project')
        if last_proj and os.path.exists(last_proj):
            self.after(200, lambda: open_project(self, last_proj))
        else:
            self.after(100, lambda: self.subtitle_panel._on_filter_apply())

    def _bind_shortcuts(self):
        """Rejestruje globalne skróty klawiszowe."""
        # Nawigacja i Projekt
        self.bind("<Control-e>", lambda e: open_recent_projects_window(self))
        self.bind("<Control-s>", lambda e: save_project(self))
        self.bind("<Control-f>", lambda e: self.subtitle_panel.search_entry.focus_set())
        self.bind("<Tab>", self._cycle_view_mode)
        self.bind("<Escape>", self._on_escape_key)

        # Audio i Wzorce
        self.bind("<Control-Y>", lambda e: VerificationWindow(self)) # Shift+Ctrl+y
        self.bind("<Control-y>", lambda e: self.subtitle_panel.verify_selected_dialogs())
        self.bind("<Control-R>",
                  lambda e: enqueue_convert_all(self))  # Shift+Ctrl+r (Tkinter widzi Shift jako wielką literę)
        self.bind("<Control-r>", lambda e: open_pattern_manager(self))
        self.bind("<Control-G>", lambda e: enqueue_generate_all(self))  # Shift+Ctrl+g
        
        # AI Tasks
        self.bind("<Control-A>", lambda e: self.open_ai_runner_global()) # Ctrl+Shift+A
        self.bind("<Control-Alt-a>", lambda e: self.open_ai_runner_selected())
        self.bind("<Control-Alt-A>", lambda e: self.open_ai_runner_selected()) # Dla pewności CapsLock/Shift

        # Kontekstowe (Linia) - bindujemy do root, ale sprawdzamy kontekst w metodach
        self.bind("<Control-space>", lambda e: self.subtitle_panel.play_selected_audio())
        self.bind("<Control-d>", lambda e: self.subtitle_panel.restore_selected_values())
        self.bind("<Control-k>", lambda e: self.subtitle_panel.accept_ai_suggestions())
        self.bind("<Control-g>", lambda e: self.subtitle_panel.generate_selected_dialogs())
        self.bind("<Control-Shift-D>", lambda e: self.subtitle_panel.set_selected_status("DONE"))

        # Ctrl+X (Usuń audio) - uwaga na konflikt z wycinaniem tekstu
        self.bind("<Control-x>", self._on_ctrl_x)

        self.bind("<Control-c>", self._on_ctrl_c)

        # Klawisz Delete (Usuń treść)
        # Bindujemy go tutaj globalnie, ale logika sprawdzi, czy nie jesteśmy w polu edycji
        self.bind("<Delete>", self._on_delete_key)

    def _cycle_view_mode(self, event=None):
        """Przełącza widok między Napisy, TTS a Sugestia SI (pomija Oryginał)."""
        current = self.view_mode.get()
        if current == "Napisy":
            new_mode = "TTS"
        elif current == "TTS":
            new_mode = "Sugestia SI"
        else:
            new_mode = "Napisy"
            
        self.subtitle_panel.view_switcher.set(new_mode)
        self.view_mode.set(new_mode)

        # Wywołujemy metodę zmiany widoku w panelu
        self.subtitle_panel._on_view_mode_change(new_mode)
        return "break"

    def open_ai_runner_global(self):
        """Otwiera okno zadań AI dla wszystkich linii."""
        if not self.lines:
             messagebox.showwarning("Brak danych", "Brak wierszy do przetworzenia.", parent=self)
             return
        
        AITaskRunnerWindow(self, self.lines, is_global=True)

    def open_ai_runner_selected(self):
        """Otwiera okno zadań AI dla zaznaczonych linii."""
        if hasattr(self, 'subtitle_panel'):
             self.subtitle_panel.open_ai_runner_selected()
        else:
             messagebox.showwarning("Błąd", "Panel napisów nie jest dostępny.", parent=self)

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

        lines: LineList = self.lines
        idx = self.selected_line_index
        mode = self.view_mode.get()
        text_to_copy = ""

        try:
            line: Line = lines[idx]
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
        self.subtitle_panel.delete_selected_dialogs()

    def _on_escape_key(self, event=None):
        """
        Obsługa klawisza ESC:
        1. Czyści wyszukiwarkę i odświeża listę.
        2. Usuwa zaznaczenie linii (jeśli istnieje) i czyści edytor.
        """
        # 1. Czyść wyszukiwarkę
        self.subtitle_panel.search_entry.delete(0, tk.END)
        patterns_apply(self)  # Odświeża listę dialogów

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
        """Obsługa Del (Usuń wiersze)."""
        widget = self.focus_get()
        # Jeśli piszemy w edytorze lub wyszukiwarce, Del ma usuwać znaki
        if isinstance(widget, (tk.Entry, ctk.CTkEntry)):
            return
            
        # Wywołaj metodę usuwania wierszy (tę samą co w menu kontekstowym)
        if self.subtitle_panel:
            self.subtitle_panel.delete_selected_rows()

    def _clear_selected_line_content(self):
        """Czyści treść aktualnie zaznaczonej linii (zastępuje pustym stringiem)."""
        if self.selected_line_index is None:
            return

        lines: LineList = self.lines
        mode = self.view_mode.get()
        idx = self.selected_line_index
        line: Line = lines[idx]

        # Nie pozwalamy edytować linii oznaczonych jako gotowe
        if getattr(line, 'status_flag', None) == "DONE":
            return

        # Nie pozwalamy edytować oryginału
        if mode == "Oryginał":
            messagebox.showinfo("Info", "Nie można edytować oryginału.", parent=self)
            return

        # Pusta wartość
        empty_val = ""

        # Zaktualizuj bezpośrednio w app.lines
        if mode == "Napisy":
            line.text = empty_val
        elif mode == "TTS":
            line.tts_text = empty_val
        
        # Zapisz do CSV
        try:
            from app.io import update_line_in_csv
            if self.loaded_path:
                update_line_in_csv(lines[idx], str(self.loaded_path))
        except Exception as e:
            print(f"Błąd zapisu do CSV: {e}")

        patterns_apply(self)
        self.subtitle_panel.set_preview(lines)
        self.set_status(f"Wyczyszczono zawartość linii {idx + 1}")

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
        open_pattern_manager(self)

    def open_add_remove_pattern(self):
        open_add_remove_pattern(self)

    def open_add_replace_pattern(self):
        open_add_replace_pattern(self)

    def open_edit_pattern(self, pattern: PatternItem, target_list: List[PatternItem]):
        open_edit_pattern(self, pattern, target_list)

    def handle_pattern_update(self, new_pattern, old_pattern, pattern_type):
        handle_pattern_update(self, new_pattern, old_pattern, pattern_type)

    def apply_patterns(self, *args):
        patterns_apply(self, *args)

    def _clear_custom_list(self, clear_type):
        _clear_custom_list(self, clear_type)

    def add_remove_pattern_from_selection(self, event=None):
        add_remove_pattern_from_selection(self, event)

    def add_replace_pattern_from_selection(self, event=None, from_menu=False):
        add_replace_pattern_from_selection(self, event, from_menu)

    # --- PROCES PRZETWARZANIA ---

    def _update_subtitle_panel_content(self):
        """Pomocnicza metoda do odświeżania panelu w zależności od trybu."""
        mode = self.view_mode.get()
        lines: LineList = self.lines
        display_list: List[str] = []

        if mode == "Oryginał":
            display_list = [line.original_text for line in lines]
        elif mode == "Napisy":
            display_list = [line.get_text() for line in lines]
        elif mode == "TTS":
            display_list = [line.get_tts_text() for line in lines]

        # Statystyki
        total_words = sum(len(line.split()) for line in display_list)
        total_chars = sum(len(line) for line in display_list)

        self.lbl_count_after.configure(text=f'Linie po: {len(lines):,}'.replace(",", " "))
        self.lbl_count_words.configure(text=f'Słowa: {total_words:,}'.replace(",", " "))
        self.lbl_count_chars.configure(text=f'Znaki: {total_chars:,}'.replace(",", " "))
        # pass Line objects instead of strings
        self.subtitle_panel.set_preview(lines)
        self.subtitle_panel.update_audio_buttons_state()


    # --- GENEROWANIE ---
    def enqueue_generate_all(self):
        enqueue_generate_all(self)

    def enqueue_convert_all(self):
        enqueue_convert_all(self)

    def _gather_tts_config(self):
        return _gather_tts_config(self)

    def _gather_converter_config(self):
        return _gather_converter_config(self)

    # --- PROJECT / SETTINGS / HELPERS ---

    def on_close(self):
        if _check_unsaved_changes(self):
            if hasattr(self, 'subtitle_panel'):
                self.subtitle_panel.stop_audio()
            if hasattr(self, 'worker'):
                self.worker.stop()
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

    def set_audio_status(self, txt):
        """Ustawia status specyficzny dla operacji audio (często przekierowuje do panelu)."""
        self.set_status(txt)

    def apply_theme_settings(self):
        ctk.set_appearance_mode(self.global_config.get('appearance_mode', 'System'))
        ctk.set_default_color_theme(self.global_config.get('color_theme', 'blue'))
        
        if hasattr(self, 'subtitle_panel'):
            # Nie musimy przekazywać trybu, panel sam go pobierze z CTK
            self.subtitle_panel.update_table_theme()

    def save_app_setting(self, param, value):
        save_app_setting(self, param, value)

    def save_global_config(self, data: dict):
        save_global_config(self, data)

    def set_project_config(self, param, value):
        set_project_config(self, param, value)
        
    def _refresh_custom_lists(self):
        if self.pattern_manager_window and self.pattern_manager_window.winfo_exists():
            self.pattern_manager_window.refresh_ui()
            
if __name__ == '__main__':
    multiprocessing.freeze_support()
    app = SubtitleStudioApp()
    app.mainloop()
