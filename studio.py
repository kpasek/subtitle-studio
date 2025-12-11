import multiprocessing
import os.path
import customtkinter as ctk
import tkinter as tk
import re
import json
import sys
import os
import shutil
import threading
import queue
import webbrowser
import requests
import subprocess
import ctypes

from pathlib import Path
from typing import List, Optional, Tuple, Dict
from tkinter import filedialog, messagebox

# --- Importy z modułów aplikacji ---
from app.pattern_manager import PatternManagerWindow
from app.settings import SettingsWindow
from app.utils import apply_remove_patterns, apply_replace_patterns, resource_path, is_installed
from app.entity import PatternItem
from app.subtitles import SubtitlePanel
from ui.generation_summary import GenerationSummaryWindow
from ui.menu import AppMenu
from ui.processing_summary import ProcessingSummaryWindow

from audio.audio_renamer import AudioRenameWindow
from audio.pattern_editor import PatternEditorWindow
from audio.deleter import AudioDeleterWindow
from audio.generation_manager import GenerationManager, GenerationJob, ConversionJob
from audio.generation_queue import GenerationQueueWindow
from ui.recent_projects import RecentProjectsWindow
from ui.shortcuts import ShortcutsWindow
from ui.game_reader_export import GameReaderExportWindow
from ui.pattern_io import PatternIOWindow
from ui.names_manager import NamesManagerWindow
from ui.audio_sync import AudioSyncWindow
from ui.audio_verification import AudioVerificationWindow

try:
    from packaging import version

    PACKAGING_AVAILABLE = True
except ImportError:
    PACKAGING_AVAILABLE = False
    print("Ostrzeżenie: Biblioteka 'packaging' nie jest zainstalowana.")

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

APP_CONFIG = os.path.join(application_path, "config.json")

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
    APP_VERSION = "0.11.0"

    def __init__(self):
        super().__init__()
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
        self.original_lines: List[str] = []
        self.processed_clean: List[str] = []
        self.processed_replace: List[str] = []

        self.names_list: List[str] = []

        # Zmienne GUI i Cache (inicjalizacja)
        self.lbl_filename: Optional[ctk.CTkLabel] = None
        self._original_lines_version = 0
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

        if hasattr(self, 'subtitle_panel'):
            # Bindujemy Prawy Przycisk Myszy (Button-3 w Windows/Linux, Button-2 w macOS czasem)
            self.subtitle_panel.editor.entry.bind("<Button-3>", self._show_editor_context_menu)

        # Sprawdzamy, czy w konfiguracji jest zapisany ostatni projekt i czy plik istnieje
        last_proj = self.global_config.get('last_project')
        if last_proj and os.path.exists(last_proj):
            # Używamy 'after', aby pozwolić GUI na pełną inicjalizację przed wczytaniem ciężkiego projektu
            self.after(100, lambda: self.open_project(last_proj))

    def _bind_shortcuts(self):
        """Rejestruje globalne skróty klawiszowe."""
        # Nawigacja i Projekt
        self.bind("<Control-e>", lambda e: self.open_recent_projects_window())
        self.bind("<Control-s>", lambda e: self.save_project())
        self.bind("<Control-f>", lambda e: self.subtitle_panel.search_entry.focus_set())
        self.bind("<Control-k>", lambda e: self.apply_processing())
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

        # Sprawdź, czy fokus jest na wewnętrznym widgecie tekstowym listy dialogów
        # (CTkTextbox w środku zawiera standardowy tk.Text dostępny przez ._textbox)
        is_preview_list = (widget == self.subtitle_panel.txt_preview._textbox)

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
            if mode == "Oryginał":
                text_to_copy = self.original_lines[idx]
            elif mode == "Napisy":
                text_to_copy = self.processed_clean[idx]
            elif mode == "TTS":
                text_to_copy = self.processed_replace[idx]
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

        # 2. Usuń zaznaczenie i wyczyść edytor
        if self.selected_line_index is not None:
            # Zapisz, jeśli były jakieś zmiany w edytorze
            if self.subtitle_panel.editor.last_saved_text:
                self.subtitle_panel.on_manual_edit_save(self.subtitle_panel.editor.entry.get())

            self.selected_line_index = None
            self.subtitle_panel.txt_preview.tag_remove("selected_line", "1.0", tk.END)
            self.subtitle_panel.editor.clear()
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

        if mode == "Napisy":
            self.manual_edits[idx] = empty_val
            self._save_manual_edits()
        elif mode == "TTS":
            self.tts_edits[idx] = empty_val
            self._save_tts_edits()

        self.apply_patterns()
        # Odśwież edytor (pokaże puste pole)
        self.subtitle_panel.on_preview_click(None)
        self.set_status(f"Wyczyszczono zawartość linii {idx + 1}")

    def open_shortcuts_window(self):
        """Otwiera okno pomocy ze skrótami."""
        ShortcutsWindow(self)

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
        else:
            self.pattern_manager_window.lift()

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

    # --- FILE & PROJECT IO ---
    def load_file(self, path: Optional[str] = None, bypass_save_check: bool = False):
        if not path:
            initial_dir = self.global_config.get('start_directory') or self._get_save_dir()
            path = filedialog.askopenfilename(title="Wybierz plik napisów",
                                              filetypes=[("Text files", "*.txt"), ("All files", "*")],
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
                self._original_lines_version += 1  # Invalidate cache

            # Wczytaj obie warstwy edycji
            self._load_manual_edits()
            self._load_tts_edits()

            self.apply_patterns()
            self.set_status(f"Wczytano {len(self.original_lines)} linii")
            self.has_unsaved_changes = False
            if self.current_project_path:
                self.set_project_config('subtitle_path', str(self.loaded_path))

        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się wczytać pliku:\n{e}")

    # --- OBSŁUGA PLIKÓW EDYCJI ---

    def _get_edits_file_path(self) -> Path | None:
        """Ścieżka dla edycji napisów (clean layer)."""
        if not self.loaded_path: return None
        return self.loaded_path.with_suffix(".edits.json")

    def _get_tts_edits_file_path(self) -> Path | None:
        """Ścieżka dla edycji TTS (replace layer)."""
        if not self.loaded_path: return None
        return self.loaded_path.with_name(self.loaded_path.stem + ".tts_edits.json")

    def _load_manual_edits(self):
        self.manual_edits = {}
        path = self._get_edits_file_path()
        if path and path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.manual_edits = {int(k): v for k, v in data.items()}
                print(f"Wczytano {len(self.manual_edits)} edycji (Napisy).")
            except Exception as e:
                print(f"Błąd edycji (Napisy): {e}")

    def _save_manual_edits(self):
        path = self._get_edits_file_path()
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self.manual_edits, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Błąd zapisu edycji (Napisy): {e}")

    def _load_tts_edits(self):
        self.tts_edits = {}
        path = self._get_tts_edits_file_path()
        if path and path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.tts_edits = {int(k): v for k, v in data.items()}
                print(f"Wczytano {len(self.tts_edits)} edycji (TTS).")
            except Exception as e:
                print(f"Błąd edycji (TTS): {e}")

    def _save_tts_edits(self):
        path = self._get_tts_edits_file_path()
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self.tts_edits, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Błąd zapisu edycji (TTS): {e}")

    # --- PROCES PRZETWARZANIA ---

    def _gather_active_patterns(self) -> tuple[List[PatternItem], List[PatternItem]]:
        """
        Zbiera wszystkie aktywne wzorce.
        """
        remove_patterns = [p for p in self.custom_remove if p.enabled]
        replace_patterns = [p for p in self.custom_replace if p.enabled]

        return remove_patterns, replace_patterns

    def _get_patterns_signature(self, patterns: List[PatternItem]):
        """Tworzy sygnaturę (hashowalną krotkę) dla listy wzorców."""
        return tuple((p.pattern, p.replace, p.case_sensitive, p.enabled) for p in patterns)

    def apply_patterns(self):
        """Przelicza linie z wykorzystaniem CACHE, aby unikać zbędnych operacji regex."""
        self.lbl_count_orig.configure(text=f'Linie org.: {len(self.original_lines):,}'.replace(",", " "))

        rem_patterns, rep_patterns = self._gather_active_patterns()

        try:
            # --- ETAP 1: Clean Patterns (Cache'owany) ---
            current_rem_sig = self._get_patterns_signature(rem_patterns)
            # Sygnatura uwzględnia wersję linii oryginalnych
            full_rem_sig = (self._original_lines_version, current_rem_sig)

            # Sprawdź czy mamy wynik w cache i czy jest aktualny
            # Tutaj używamy poprawnej nazwy zmiennej z __init__
            if self._cache_clean_base is None or full_rem_sig != self._last_remove_signature:
                self._cache_clean_base = apply_remove_patterns(self.original_lines, rem_patterns)
                self._last_remove_signature = full_rem_sig

            # Zastosuj edycje manualne na bazie wyniku z cache
            self.processed_clean = list(self._cache_clean_base)
            for idx, text in self.manual_edits.items():
                if 0 <= idx < len(self.processed_clean):
                    self.processed_clean[idx] = text

            # --- ETAP 2: Replace Patterns (Cache'owany) ---
            input_hash = hash(tuple(self.processed_clean))
            current_rep_sig = self._get_patterns_signature(rep_patterns)

            full_rep_sig = (input_hash, current_rep_sig)

            if self._cache_replace_result is None or full_rep_sig != self._last_replace_signature:
                self._cache_replace_result = apply_replace_patterns(self.processed_clean, rep_patterns)
                self._last_replace_signature = full_rep_sig

            # Zastosuj edycje manualne TTS
            self.processed_replace = list(self._cache_replace_result)
            for idx, text in self.tts_edits.items():
                if 0 <= idx < len(self.processed_replace):
                    self.processed_replace[idx] = text

        except re.error as e:
            messagebox.showerror('Błąd regex', f'Błąd w wyrażeniu regularnym:\n{e}')
            return
        except Exception as e:
            # Ważne: logowanie błędów, żeby wiedzieć co poszło nie tak
            print(f"Error applying patterns: {e}")
            import traceback
            traceback.print_exc()
            return

        # Wybierz listę do wyświetlenia
        mode = self.view_mode.get()
        lines_to_show = []
        if mode == "Oryginał":
            lines_to_show = self.original_lines
        elif mode == "Napisy":
            lines_to_show = self.processed_clean
        else:  # TTS
            lines_to_show = self.processed_replace

        # Statystyki
        total_words = sum(len(line.split()) for line in lines_to_show)
        total_chars = sum(len(line) for line in lines_to_show)

        self.lbl_count_after.configure(text=f'Linie po: {len(self.processed_clean):,}'.replace(",", " "))
        self.lbl_count_words.configure(text=f'Słowa: {total_words:,}'.replace(",", " "))
        self.lbl_count_chars.configure(text=f'Znaki: {total_chars:,}'.replace(",", " "))

        # Odśwież widok w panelu
        self.subtitle_panel.set_preview(lines_to_show)
        self.subtitle_panel.update_audio_buttons_state()

    def apply_processing(self):
        """Zatwierdzenie zmian (okno podsumowania)."""
        if not self.original_lines:
            messagebox.showwarning('Brak pliku', 'Najpierw wczytaj plik z napisami.')
            return

        rem_patterns, _ = self._gather_active_patterns()
        simulated_lines = apply_remove_patterns(self.original_lines, rem_patterns)

        changes_count = 0
        for i, (orig, new) in enumerate(zip(self.original_lines, simulated_lines)):
            if i in self.manual_edits:
                changes_count += 1
            elif orig != new:
                changes_count += 1

        ProcessingSummaryWindow(
            self, len(self.original_lines), changes_count,
            manual_edits_count=len(self.manual_edits),
            callback=self._finalize_processing
        )

    def _finalize_processing(self, remove_empty: bool, remove_duplicates: bool):
        """
        Zatwierdza zmiany z okna podsumowania.
        Implementuje ścisłe wiązanie ID linii z plikami audio przed przetworzeniem.
        """
        rem_patterns, rep_patterns = self._gather_active_patterns()

        # 1. Przygotuj bazę tekstową (Regex) - to nie zmienia indeksów
        base_processed = apply_remove_patterns(self.original_lines, rem_patterns)

        # Nałóż edycje manualne
        for idx, text in self.manual_edits.items():
            if 0 <= idx < len(base_processed):
                base_processed[idx] = text

        # 2. IN-MEMORY BINDING: Zbuduj strukturę danych wiążącą linię z jej plikami audio
        # Każdy element to słownik: { 'old_id': int, 'text': str, 'audio_files': List[Path] }
        lines_data = []

        # Helper do szukania plików dla danego ID
        def find_files_for_id(ident: int) -> List[Path]:
            found = []
            if not self.audio_dir: return found

            # Sprawdź główne rozszerzenia
            for ext in ['.wav', '.mp3']:
                f = self.audio_dir / f"output1 ({ident}){ext}"
                if f.exists(): found.append(f)

            # Sprawdź folder ready
            ready_dir = self.audio_dir / "ready"
            if ready_dir.exists():
                for ext in ['.ogg', '.mp3']:
                    f = ready_dir / f"output1 ({ident}){ext}"
                    if f.exists(): found.append(f)

            return found

        for i, text in enumerate(base_processed):
            old_id = i + 1
            entry = {
                'old_id': old_id,
                'text': text,
                'audio_files': find_files_for_id(old_id),  # Tu następuje "przypięcie" plików
                'keep': True
            }
            lines_data.append(entry)

        # 3. Logika filtrowania (oznaczamy co usunąć)
        seen = set()
        for entry in lines_data:
            text = entry['text']

            if remove_empty and not text.strip():
                entry['keep'] = False

            if remove_duplicates and entry['keep']:  # Sprawdzamy tylko jeśli jeszcze nie odpadło
                if text in seen:
                    entry['keep'] = False
                elif text.strip():
                    seen.add(text)

        # 4. Generowanie nowej listy linii i planu dla plików
        final_lines = []
        audio_operations = []  # Lista krotek dla AudioSyncWindow

        new_idx_counter = 1

        for entry in lines_data:
            if entry['keep']:
                final_lines.append(entry['text'])

                # Jeśli linia zostaje, sprawdzamy czy zmienił się jej numer
                new_id = new_idx_counter
                new_idx_counter += 1

                if new_id != entry['old_id']:
                    # Linia zmienia numer -> Przenieś WSZYSTKIE jej pliki
                    for src in entry['audio_files']:
                        # Oblicz nową nazwę zachowując rozszerzenie i folder
                        is_ready_folder = src.parent.name == "ready"
                        if is_ready_folder:
                            dst = self.audio_dir / "ready" / f"output1 ({new_id}){src.suffix}"
                        else:
                            dst = self.audio_dir / f"output1 ({new_id}){src.suffix}"

                        audio_operations.append(('rename', src, dst))
            else:
                # Linia usuwana -> Usuń jej pliki
                for src in entry['audio_files']:
                    audio_operations.append(('delete', src, None))

        # 5. Wykonanie zmian

        # Jeśli są operacje na plikach, uruchom okno synchronizacji
        if audio_operations:
            if self.audio_dir and self.audio_dir.exists():
                AudioSyncWindow(self, audio_operations)
            else:
                messagebox.showwarning("Błąd",
                                       "Katalog audio nie jest dostępny, ale wykryto zmiany wymagające synchronizacji.")

        # Aktualizacja stanu aplikacji
        if len(final_lines) != len(base_processed):
            self.processed_clean = final_lines
            self.manual_edits = {}
            self.tts_edits = {}
            self.set_status(
                f'Zatwierdzono. Usunięto {len(base_processed) - len(final_lines)} linii. Przygotowano {len(audio_operations)} operacji na plikach.')
        else:
            self.processed_clean = base_processed
            self.set_status('Zatwierdzono zmiany. Brak linii do usunięcia.')

        self._refresh_custom_lists()
        self.mark_as_unsaved()

        self._cache_replace_result = None
        self._last_replace_signature = None
        self.apply_patterns()

    # --- GENEROWANIE ---

    def _prepare_job_dependencies(self) -> bool:
        if not self.audio_dir or not self.audio_dir.is_dir():
            messagebox.showwarning("Brak katalogu", "Najpierw wybierz katalog audio.", parent=self)
            return False
        if not self.current_project_path:
            messagebox.showwarning("Brak projektu", "Zapisz projekt przed dodaniem do kolejki.", parent=self)
            return False
        if not self.processed_replace:
            messagebox.showwarning("Brak danych", "Najpierw przetwórz napisy.", parent=self)
            return False
        return True

    def enqueue_generate_single(self):
        if self.selected_line_index is None:
            messagebox.showwarning("Brak zaznaczenia", "Najpierw wybierz linię.", parent=self)
            return

        if not self._prepare_job_dependencies(): return

        identifier = str(self.selected_line_index + 1)
        try:
            # Ważne: pobieramy tekst z processed_replace, który zawiera już tts_edits
            text = self.processed_replace[self.selected_line_index]
            lines_to_gen = [(identifier, text)]
        except (IndexError, ValueError):
            return

        tts_model = self._get_active_tts_model_name()
        if not tts_model:
            messagebox.showerror("Błąd", "Brak modelu TTS.")
            return

        job = GenerationJob(
            project_path=f"POJEDYNCZY ({identifier}) - {self.current_project_path.name}",
            audio_dir=self.audio_dir,
            lines_to_generate=lines_to_gen,
            tts_model_name=tts_model,
            tts_config=self._gather_tts_config(),
            converter_config=self._gather_converter_config()
        )
        GenerationManager.get_instance().add_job(job)
        self.set_status(f"Dodano zadanie (linia {identifier}) do kolejki.")

    def enqueue_generate_all(self):
        if not self._prepare_job_dependencies(): return

        # 1. Analiza stanu
        total_items = len(self.processed_replace)
        existing_items = 0

        for i in range(total_items):
            identifier = str(i + 1)
            raw_wav = self.audio_dir / f"output1 ({identifier}).wav"
            raw_mp3 = self.audio_dir / f"output1 ({identifier}).mp3"
            if raw_wav.exists() or raw_mp3.exists():
                existing_items += 1

        # 2. Wyświetl okno podsumowania
        GenerationSummaryWindow(
            self,
            "Generowanie dialogów",
            total_items,
            existing_items,
            callback=self._execute_generate_all
        )

    def _execute_generate_all(self, overwrite: bool):
        """Callback po zatwierdzeniu generowania."""
        tts_model = self._get_active_tts_model_name()
        if not tts_model: return

        dialogs_to_generate = []

        # Iterujemy po wszystkich liniach, aby zachować ciągłość ID (i + 1)
        for i, text in enumerate(self.processed_replace):
            identifier = str(i + 1)
            text = text.strip()

            if not text:
                continue

            # Jeśli NIE nadpisujemy, to sprawdź czy plik istnieje
            if not overwrite:
                raw_wav = self.audio_dir / f"output1 ({identifier}).wav"
                raw_mp3 = self.audio_dir / f"output1 ({identifier}).mp3"

                # Jeśli którykolwiek istnieje, pomiń
                if raw_wav.exists() or raw_mp3.exists():
                    continue

            dialogs_to_generate.append((identifier, text))

        if not dialogs_to_generate:
            messagebox.showinfo("Info", "Brak dialogów do wygenerowania (wszystkie istnieją lub są puste).")
            return

        job = GenerationJob(
            project_path=self.current_project_path.name,
            audio_dir=self.audio_dir,
            lines_to_generate=dialogs_to_generate,
            tts_model_name=tts_model,
            tts_config=self._gather_tts_config(),
            converter_config=self._gather_converter_config()
        )
        GenerationManager.get_instance().add_job(job)
        self.show_generation_queue()
        self.set_status(f"Dodano {len(dialogs_to_generate)} linii do kolejki.")

    def enqueue_convert_all(self):
        if not self.audio_dir or not self.audio_dir.is_dir():
            messagebox.showwarning("Brak katalogu", "Najpierw wybierz katalog audio.", parent=self)
            return

        # 1. Analiza stanu (ile plików źródłowych vs ile w ready)
        # Liczymy pliki źródłowe (WAV/MP3) które mają odpowiadające identyfikatory
        source_files = list(self.audio_dir.glob("output1 (*).wav")) + list(self.audio_dir.glob("output1 (*).mp3"))
        total_source = len(source_files)

        ready_dir = self.audio_dir / "ready"
        existing_target = 0
        if ready_dir.exists():
            existing_target = len(list(ready_dir.glob("*.ogg"))) + len(list(ready_dir.glob("*.mp3")))

        # 2. Okno podsumowania
        GenerationSummaryWindow(
            self,
            "Konwersja audio",
            total_source,
            existing_target,
            callback=self._execute_convert_all
        )

    def _execute_convert_all(self, overwrite: bool):
        """Callback po zatwierdzeniu konwersji."""

        # Jeśli overwrite=True, usuń wszystkie pliki w 'ready' przed startem
        if overwrite:
            ready_dir = self.audio_dir / "ready"
            if ready_dir.exists():
                try:
                    for f in ready_dir.glob("*.ogg"):
                        os.remove(f)
                except Exception as e:
                    print(f"Błąd czyszczenia katalogu ready: {e}")

        # Uruchomienie konwersji (tak jak wcześniej)
        if os.name == 'nt':
            converter_config = self._gather_converter_config()
            workers = converter_config.get("conversion_workers", 4)
            filters = converter_config.get("ffmpeg_filters", {})
            fmt = converter_config.get("audio_output_format", "ogg")

            if getattr(sys, 'frozen', False):
                exe_path = "converter.exe"
            else:
                exe_path = str(Path(__file__).parent / "audio" / "converter.py")

            cmd = [
                exe_path,
                "--path", str(self.audio_dir),
                "--workers", str(workers),
                "--format", fmt,
                "--filters", json.dumps(filters)
            ]
            if not getattr(sys, 'frozen', False):
                cmd.insert(0, sys.executable)

            try:
                creation_flags = subprocess.CREATE_NEW_CONSOLE
                subprocess.Popen(cmd, creationflags=creation_flags)
                self.set_status("Rozpoczęto konwersję w nowym procesie.")
            except Exception as e:
                messagebox.showerror("Błąd uruchamiania konwersji", str(e), parent=self)
        else:
            if not self.current_project_path:
                messagebox.showwarning("Brak projektu", "Zapisz projekt przed dodaniem do kolejki.", parent=self)
                return
            job = ConversionJob(
                project_path=f"KONWERSJA - {self.current_project_path.name}",
                audio_dir=self.audio_dir,
                converter_config=self._gather_converter_config()
            )
            GenerationManager.get_instance().add_job(job)
            self.show_generation_queue()
            self.set_status("Dodano zadanie konwersji audio do kolejki.")

    # --- PROJECT / SETTINGS / HELPERS ---

    def open_project(self, path: str | None = None):
        """Otwiera plik projektu .json."""
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

            self._update_recent_projects(str(self.current_project_path))

            self.names_list = cfg.get("names_list", [])

            all_vars = self.builtin_remove_state + self.builtin_replace_state
            traces = {}
            for var in all_vars:
                if var.trace_info():
                    trace_id = var.trace_info()[0][1]
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

            self.custom_remove = [PatternItem.from_json(x) for x in cfg.get("custom_remove", [])]
            self.custom_replace = [PatternItem.from_json(x) for x in cfg.get("custom_replace", [])]
            self._refresh_custom_lists()

            subtitle_path = cfg.get("subtitle_path")
            if subtitle_path and Path(subtitle_path).exists():
                self.load_file(subtitle_path, bypass_save_check=True)
            else:
                self.original_lines = []
                self._original_lines_version += 1  # Invalidate cache
                self.apply_patterns()
                self.lbl_filename.configure(text="Brak wczytanego pliku")

            audio_path_str = cfg.get("audio_path")
            self.audio_dir = Path(audio_path_str) if audio_path_str else None

            self.set_status(f"Wczytano projekt: {self.current_project_path.name}")
            self.save_app_setting('last_project', path)
            self.has_unsaved_changes = False
            self.lbl_filename.configure(text=os.path.basename(path))

            self.subtitle_panel.update_audio_buttons_state()

        except Exception as e:
            messagebox.showerror("Błąd wczytywania projektu", f"Nie udało się wczytać konfiguracji:\n{e}")
            self.current_project_path = None
            self.project_config = {}
            self.has_unsaved_changes = False
        self._refresh_custom_lists()

    def close_project(self):
        """Zamyka obecny projekt (restartuje apkę)."""
        if not self._check_unsaved_changes():
            return
        try:
            self.save_app_setting('last_project', None)
            os.execl(sys.executable, sys.executable, *sys.argv)
        except Exception as e:
            messagebox.showerror("Błąd restartu", f"Nie udało się zrestartować aplikacji:\n{e}")

    def save_project(self, cfg: dict | None = None):
        if not self.current_project_path:
            return self.save_project_as()
        final_cfg = self._gather_project_config()
        if cfg:
            final_cfg.update(cfg)
        self.project_config = final_cfg
        try:
            with open(self.current_project_path, "w", encoding="utf-8") as f:
                json.dump(final_cfg, f, indent=2, ensure_ascii=False)
            self.set_status(f"Zapisano projekt: {self.current_project_path.name}")
            self.has_unsaved_changes = False
        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się zapisać konfiguracji:\n{e}")

    def save_project_as(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")],
                                            initialdir=self.global_config.get('start_directory'))
        if not path:
            return
        self.current_project_path = Path(path)
        self.save_project()

    def set_project_config(self, param, value):
        if self.project_config is None: self.project_config = {}
        if self.project_config.get(param) != value:
            self.project_config[param] = value
            self.mark_as_unsaved()
            if self.current_project_path: self.save_project()

    def _gather_project_config(self) -> dict:
        current_cfg = self.project_config.copy() if self.project_config else {}
        current_cfg.update({
            "builtin_remove_state": [bool(v.get()) for v in self.builtin_remove_state],
            "builtin_replace_state": [bool(v.get()) for v in self.builtin_replace_state],
            "custom_remove": [p.to_json() for p in self.custom_remove],
            "custom_replace": [p.to_json() for p in self.custom_replace],
            "subtitle_path": str(self.loaded_path) if self.loaded_path else None,
            "audio_path": str(self.audio_dir.absolute()) if self.audio_dir else None,
            "names_list": self.names_list,
            "active_tts_model": self.project_config.get('active_tts_model', 'XTTS'),
            "base_audio_speed": self.project_config.get('base_audio_speed', 1.1)
        })
        return current_cfg

    def _load_app_config(self, only_config=False):
        if os.path.exists(APP_CONFIG):
            if os.path.exists(APP_CONFIG):
                try:
                    with open(APP_CONFIG, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    self.global_config = cfg
                except Exception as e:
                    print(f"Błąd wczytywania configu: {e}")
                    self.global_config = {}  # Fallback w razie błędu odczytu
            else:
                self.global_config = {}

    def save_app_setting(self, param, value):
        self.global_config.update({param: value})
        try:
            with open(APP_CONFIG, "w", encoding="utf-8") as f:
                json.dump(self.global_config, f, indent=2)
        except Exception:
            pass

    def save_global_config(self, data: dict):
        """
        Zapisuje słownik ustawień przekazany z SettingsWindow.
        Iteruje po kluczach, aby bezpiecznie zaktualizować konfigurację,
        nie usuwając innych ustawień (np. recent_projects).
        """
        # Iteracja i aktualizacja klucz po kluczu
        for key, value in data.items():
            self.global_config[key] = value

        # Zapisz do pliku
        try:
            with open(APP_CONFIG, "w", encoding="utf-8") as f:
                json.dump(self.global_config, f, indent=4)
            self.set_status("Zapisano ustawienia aplikacji.")

            # Zastosuj motyw od razu, jeśli został zmieniony
            self.apply_theme_settings()

        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się zapisać ustawień:\n{e}")

    def _check_unsaved_changes(self) -> bool:
        if self.has_unsaved_changes and self.current_project_path:
            msg = "Masz niezapisane zmiany w projekcie. Czy chcesz je zapisać?"
            result = messagebox.askyesnocancel("Niezapisane zmiany", msg, parent=self)
            if result is True:
                self.save_project()
            elif result is None:
                return False
        return True

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
            'local_api_url': self.global_config.get('local_api_url'),
            'xtts_voice_path': self.project_config.get('xtts_voice_path') or self.global_config.get('xtts_voice_path'),
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
            text = self.processed_replace[self.selected_line_index]
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
            text = self.processed_replace[self.selected_line_index].strip()
            if not text: return
            win = PatternEditorWindow(self, 'replace', self.handle_pattern_update, None)
            win.ent_pattern.insert(0, text)
            win.ent_replace.insert(0, text)
            win.var_case_sensitive.set(True)
            if from_menu: win.lift()
        except IndexError:
            pass

    def _check_for_updates(self):
        if not PACKAGING_AVAILABLE: return
        API_URL = "https://api.github.com/repos/kpasek/subtitle-studio/releases/latest"
        try:
            response = requests.Session().get(API_URL, timeout=10)
            response.raise_for_status()
            data = response.json()
            latest_tag = data.get('tag_name')
            if latest_tag and version.parse(latest_tag) > version.parse(self.APP_VERSION):
                download_url = f"https://github.com/kpasek/subtitle-studio/releases/download/{latest_tag}/SubtitleStudioWindows.zip" if sys.platform == "win32" else data.get(
                    'html_url')
                self.latest_version_info = (latest_tag, download_url)
                self.queue.put(self._show_update_button)
        except Exception:
            pass

    def _show_update_button(self):
        if self.latest_version_info and self.update_button:
            self.update_button.configure(text=f"Nowa Wersja! ({self.latest_version_info[0]})")
            self.update_button.pack(side="left", padx=5)
            self.lbl_filename.pack_configure(side="left", anchor="w", padx=5)

    def _download_update(self):
        if self.latest_version_info:
            webbrowser.open(self.latest_version_info[1], new=2)

    def show_about_window(self):
        about_win = ctk.CTkToplevel(self)
        about_win.title("O programie")
        about_win.geometry("400x200")

        # Kluczowe linie naprawiające chowanie się okna:
        about_win.transient(self)
        about_win.lift()
        about_win.focus_force()

        ctk.CTkLabel(about_win, text=APP_TITLE, font=("", 20, "bold")).pack(pady=10)
        ctk.CTkLabel(about_win, text=f"Wersja: {self.APP_VERSION}").pack()
        ctk.CTkLabel(about_win, text="Autor: Kamil Pasek").pack()

        ctk.CTkButton(about_win, text="Zamknij", command=about_win.destroy).pack(pady=20)

    # Proxy dla metod z menu
    def open_audio_deleter(self):
        if not self.processed_clean: return messagebox.showwarning("Brak danych", "Najpierw przetwórz.", parent=self)
        if not self.audio_dir: return messagebox.showwarning("Brak katalogu", "Ustaw katalog audio.", parent=self)

        AudioDeleterWindow(self, self.processed_clean, str(self.audio_dir)).grab_set()

    def open_global_settings(self):
        SettingsWindow(self, self.torch_installed, mode='global').grab_set()

    def open_project_settings(self):
        if not self.current_project_path: return messagebox.showwarning("Brak projektu", "Zapisz projekt.", parent=self)
        SettingsWindow(self, self.torch_installed, mode='project').grab_set()

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
        if not self.processed_clean: return
        path = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Text files', '*.txt')])
        if path:
            with open(path, 'w', encoding='utf-8') as f: f.write('\n'.join(self.processed_clean))
            messagebox.showinfo('Gotowe', f'Zapisano: {path}')

    def download_replace(self):
        if not self.processed_replace: return
        path = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Text files', '*.txt')])
        if path:
            with open(path, 'w', encoding='utf-8') as f: f.write('\n'.join(self.processed_replace))
            messagebox.showinfo('Gotowe', f'Zapisano: {path}')

    def generate_game_reader_preset(self):
        """Otwiera okno konfiguracji eksportu do Game Readera."""
        if not self.processed_replace:
            messagebox.showwarning('Brak danych', 'Brak przetworzonych napisów do wyeksportowania.', parent=self)
            return

        if not self.audio_dir:
            messagebox.showwarning('Brak audio', 'Nie wybrano katalogu audio w projekcie.', parent=self)
            return

        # Otwórz nowe okno konfiguracji
        GameReaderExportWindow(self)

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
        """Aktualizuje listę ostatnich projektów w configu."""
        recents = self.global_config.get('recent_projects', [])
        # Usuń jeśli już jest (żeby przenieść na górę)
        if path in recents:
            recents.remove(path)
        # Dodaj na początek
        recents.insert(0, path)
        # Limit np. do 15
        recents = recents[:15]

        self.save_app_setting('recent_projects', recents)

    def open_recent_projects_window(self):
        """Otwiera okno z listą ostatnich projektów."""
        recents = self.global_config.get('recent_projects', [])
        RecentProjectsWindow(
            self,
            recents,
            on_open_callback=self.open_project,
            on_delete_callback=self._remove_recent_project,
            on_clear_callback=self._clear_recent_projects
        )

    def _remove_recent_project(self, path: str):
        recents = self.global_config.get('recent_projects', [])
        if path in recents:
            recents.remove(path)
            self.save_app_setting('recent_projects', recents)

    def _clear_recent_projects(self):
        self.save_app_setting('recent_projects', [])

    def open_names_manager(self):
        """Otwiera okno zarządzania imionami."""
        NamesManagerWindow(self)

    def _show_editor_context_menu(self, event):
        """Pokazuje menu kontekstowe w edytorze."""
        # Tworzymy standardowe menu Tkinter
        menu = tk.Menu(self, tearoff=0)

        # Opcje edycyjne (standardowe, bo nadpisujemy domyślne menu systemowe)
        menu.add_command(label="Wytnij", command=lambda: self.subtitle_panel.editor.entry.event_generate("<<Cut>>"))
        menu.add_command(label="Kopiuj", command=lambda: self.subtitle_panel.editor.entry.event_generate("<<Copy>>"))
        menu.add_command(label="Wklej", command=lambda: self.subtitle_panel.editor.entry.event_generate("<<Paste>>"))
        menu.add_separator()

        # Nasza nowa opcja
        menu.add_command(label="Dodaj do imion", command=self._add_selected_text_to_names)

        menu.tk_popup(event.x_root, event.y_root)

    def _add_selected_text_to_names(self):
        """Pobiera zaznaczony tekst w edytorze i dodaje do listy imion."""
        try:
            # selection_get() rzuca wyjątek, jeśli brak zaznaczenia
            selected_text = self.subtitle_panel.editor.entry.selection_get()
            selected_text = selected_text.strip()

            if not selected_text:
                return

            if selected_text in self.names_list:
                # Zamiast messagebox, info na pasku statusu
                self.set_status(f"Ignoruję: Imię '{selected_text}' już jest na liście.")
            else:
                self.names_list.append(selected_text)
                self.mark_as_unsaved()
                # Zamiast messagebox, info na pasku statusu
                self.set_status(f"Dodano '{selected_text}' do listy imion.")

        except tk.TclError:
            # Wyrzuca błąd, gdy nic nie jest zaznaczone -> ignorujemy to
            pass
        except Exception as e:
            print(f"Błąd dodawania imienia: {e}")

    def open_audio_verification(self):
        if not self.audio_dir:
            messagebox.showwarning("Brak audio", "Najpierw wybierz katalog audio.", parent=self)
            return

        # Używamy processed_replace (tekst TTS) jeśli dostępny, bo on odpowiada temu co lektor czyta.
        # Jeśli nie, używamy clean, a ostatecznie oryginału.
        lines = self.processed_replace if self.processed_replace else (
            self.processed_clean if self.processed_clean else self.original_lines)

        if not lines:
            messagebox.showwarning("Brak tekstu", "Brak napisów do weryfikacji.", parent=self)
            return

        AudioVerificationWindow(self, self.audio_dir, lines)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    app = SubtitleStudioApp()
    app.mainloop()
