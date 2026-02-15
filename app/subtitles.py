import shutil
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import subprocess
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from app.entity import Line
from tkinter import messagebox
import threading
import time
import shutil

from app.formatter import format_percent, normalize_to_percent
from app.io import (update_line_in_csv, update_lines_in_csv, delete_lines_from_csv, 
                    get_audio_candidates)
from app.patterns import (apply_patterns, add_replace_pattern_from_selection)
from app.update import download_update
from app.project import get_active_tts_model_name, gather_tts_config, gather_converter_config

# Spróbuj załadować VerificationManager
try:
    from audio.verification_manager import VerificationManager, VerificationJob
except ImportError:
    VerificationManager = None
    VerificationJob = None

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
        self._suppress_refresh = False
        self.selected_line_indices = []  # Lista zaznaczonych indeksów wierszy
        self.item_line_map: Dict[str, Line] = {}
        self.filter_spec = {}

        # Konfiguracja kolumn - tutaj można łatwo dodawać nowe kolumny w przyszłości
        self.columns_config = [
            {"id": "content", "text": "Tekst", "width": 600, "anchor": "w", "stretch": True},
            {"id": "status", "text": "Status", "width": 80, "anchor": "center", "stretch": False},
            {"id": "duration", "text": "Czas", "width": 80, "anchor": "center", "stretch": False},
            {"id": "char_count", "text": "CHAR", "width": 90, "anchor": "center", "stretch": False},
            {"id": "cps", "text": "CPS", "width": 70, "anchor": "center", "stretch": False},
            {"id": "similarity", "text": "SIM %", "width": 80, "anchor": "center", "stretch": False},
            {"id": "hallucination", "text": "HALU!", "width": 70, "anchor": "center", "stretch": False},
            {"id": "audio_file", "text": "Plik", "width": 250, "anchor": "w", "stretch": False},
        ]

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # --- Weryfikacja audio ---
        self.ver_running = False
        self.ver_stop_event = threading.Event()
        self.ver_ffprobe_path = shutil.which('ffprobe')
        self.ver_modified_buffer = []
        self.ver_last_save_time = 0

        self._create_widgets()

    def _create_widgets(self):
        # 1. Top Panel (Actions + View + Info) - merged into one line
        top_frame = ctk.CTkFrame(self)
        top_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5), padx=5)
        
        # --- Left side: Action Buttons ---
        self.generate_button = ctk.CTkButton(top_frame, text="⚙️ Generuj", width=80,
                                             command=self.generate_selected_dialogs, state="disabled",
                                             fg_color="#2E8B57", hover_color="#1E613B")
        self.generate_button.pack(side="left", padx=4, pady=5)

        self.btn_ai_tasks = ctk.CTkButton(top_frame, text="✨ Zadania SI", width=100,
                                          command=self.open_ai_runner_selected,
                                          fg_color="#8e44ad", hover_color="#9b59b6")
        self.btn_ai_tasks.pack(side="left", padx=4, pady=5)

        self.verify_button = ctk.CTkButton(top_frame, text="✓ Weryfikuj", width=100,
                                           command=self.verify_selected_dialogs, state="disabled",
                                           fg_color="#1E90FF", hover_color="#4169E1")
        self.verify_button.pack(side="left", padx=4, pady=5)
        

        # Restore Button z tooltipem o skrócie
        self.btn_restore = ctk.CTkButton(
            top_frame,
            text="↺ Przywróć",
            width=100,
            command=self.restore_selected_values,
            fg_color="#7f8c8d",
            hover_color="#95a5a6"
        )
        self.btn_restore.pack(side="left", padx=4, pady=5)
        self.btn_restore._text_label.configure(text="↺ Przywróć (Ctrl+D)")

        # Button: Oznacz jako Gotowe
        self.btn_done = ctk.CTkButton(
            top_frame,
            text="✅ Gotowe",
            width=100,
            command=lambda: self.set_selected_status("DONE"),
            fg_color="#27ae60",
            hover_color="#219150"
        )
        self.btn_done.pack(side="left", padx=4, pady=5)
        self.btn_done._text_label.configure(text="✅ Gotowe (Ctrl+Shift+D)")

        self.delete_all_button = ctk.CTkButton(top_frame, text="🗑️ Usuń audio", width=100,
                                               command=self.delete_selected_dialogs, state="disabled",
                                               fg_color="#C51616", hover_color="#920F0F")
        self.delete_all_button.pack(side="left", padx=4, pady=5)

        # --- Right/Middle side: View & Info ---
        ctk.CTkLabel(top_frame, text="|", text_color="gray").pack(side="left", padx=(10, 5))

        ctk.CTkLabel(top_frame, text="Widok:").pack(side="left", padx=(5, 5))
        self.view_switcher = ctk.CTkSegmentedButton(
            top_frame,
            values=["Oryginał", "Napisy", "TTS"],
            variable=self.app.view_mode,
            command=self._on_view_mode_change,
            width=180
        )
        self.view_switcher.pack(side="left", padx=5, pady=5)

        self.app.update_button = ctk.CTkButton(top_frame, text="Nowa wersja!",
                                               command=lambda: download_update(self.app),
                                               fg_color="#006400", hover_color="#004d00",
                                               width=100)
        self.app.update_button.pack(side="left", padx=5)
        self.app.update_button.pack_forget()

        self.app.lbl_filename = ctk.CTkLabel(top_frame, text="Brak wczytanego pliku")
        self.app.lbl_filename.pack(side="left", anchor="w", padx=10)


        # 2. Search Frame (Filter + Search Entry + Search Button)
        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.grid(row=1, column=0, sticky="ew", pady=(0, 5), padx=5)

        self.filter_button = ctk.CTkButton(search_frame, text="Filtruj", command=self.open_filter_window, width=80)
        self.filter_button.pack(side="left", padx=(0, 5))

        self.search_button = ctk.CTkButton(search_frame, text="Odśwież", width=80,
                           command=lambda: apply_patterns(self.app))
        self.search_button.pack(side="left", padx=(0, 5))

        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="Szukaj tekstu...")
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.search_entry.bind("<Return>", lambda event: apply_patterns(self.app))
        self.search_entry.bind("<Control-BackSpace>", lambda event: self.search_entry.delete(0, tk.END))


        # 3. Table Frame
        table_frame = ctk.CTkFrame(self, fg_color="transparent")
        table_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=(0, 5))
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # Pobieramy ID kolumn z konfiguracji
        column_ids = [col["id"] for col in self.columns_config]

        self.tree = ttk.Treeview(table_frame, columns=column_ids, show="headings", selectmode="extended")

        # Konfiguracja nagłówków i kolumn na podstawie self.columns_config
        for col_conf in self.columns_config:
            # add click-to-sort handler
            self.tree.heading(col_conf["id"], text=col_conf["text"], command=lambda c=col_conf["id"]: self._sort_by_column(c))
            self.tree.column(
                col_conf["id"],
                width=col_conf["width"],
                anchor=col_conf["anchor"],
                stretch=col_conf.get("stretch", True)
            )

        self.tree.grid(row=0, column=0, sticky="nsew")

        # Scrollbar
        self.scrollbar = ctk.CTkScrollbar(table_frame, orientation="vertical", command=self.tree.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=self.scrollbar.set)

        # Eventy
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-Button-1>", self.play_selected_audio)
        self.tree.bind("<Button-3>", self._show_context_menu)
        # Obsługa Alt+Klik (edycja inline) zamiast Ctrl+Klik (konflikt z multi-select)
        self.tree.bind("<Alt-Button-1>", self._start_inline_edit)
        # Dodatkowe skróty klawiszowe dla tabeli
        self.tree.bind("<F2>", self._start_inline_edit)
        self.tree.bind("<Return>", self._start_inline_edit)
        self.tree.bind("<space>", self.play_selected_audio)
        self.tree.bind("<Control-a>", self.select_all_visible)

        # Zmienne do edycji inline
        self.inline_edit_entry = None
        self.inline_edit_item = None

        # Inicjalizacja stylu tabeli
        self.update_table_theme()

    def update_table_theme(self, mode: str = None):
        """Aktualizuje kolory tabeli (Treeview) w zależności od motywu (Light/Dark)."""
        
        # Próbujemy pobrać efektywny tryb z CustomTkinter (widgetu)
        # _get_appearance_mode() zwraca 'light' lub 'dark'
        if hasattr(self, "_get_appearance_mode"):
            effective_mode = self._get_appearance_mode()
        else:
            # Fallback dla starszych wersji CTK lub jeśli metoda jest niedostępna
            effective_mode = mode or ctk.get_appearance_mode()

        style = ttk.Style()
        style.theme_use("clam")

        if effective_mode.lower() == "light":
            bg_color = "#ffffff"
            fg_color = "#000000"
            field_bg = "#ffffff"
            heading_bg = "#e1e1e1"
            heading_fg = "#000000"
            heading_active = "#d1d1d1"
            selected_bg = "#3a7ebf"
            selected_fg = "white"
            border_color = "#e1e1e1"
        else:
            # Dark mode (default)
            bg_color = "#2b2b2b"
            fg_color = "white"
            field_bg = "#2b2b2b"
            heading_bg = "#1c1c1c"
            heading_fg = "white"
            heading_active = "#252525"
            selected_bg = "#1f538d"
            selected_fg = "white"
            border_color = "#2b2b2b"

        style.configure("Treeview",
                        background=bg_color,
                        foreground=fg_color,
                        fieldbackground=field_bg,
                        bordercolor=border_color,
                        lightcolor=border_color,
                        darkcolor=border_color,
                        rowheight=25)


        style.configure("Treeview.Heading",
                        background=heading_bg,
                        foreground=heading_fg,
                        relief="flat")

        style.map("Treeview.Heading",
                  background=[('active', heading_active)])

        style.map("Treeview",
                  background=[('selected', selected_bg)],
                  foreground=[('selected', selected_fg)])

    def _on_view_mode_change(self, value):
        # Optimization: Do not re-apply patterns on simple view switch. 
        # Data in 'text'/'tts_text' should already be consistent.
        # apply_patterns(self.app)  
        self.set_preview(self.app.lines)
        from app.project import save_app_setting
        save_app_setting(self.app, 'last_view_mode', value)



    def _sort_by_column(self, col_id: str):
        """Sortuje `self.app.lines` według kolumny, toggle asc/desc."""
        # Zapamiętaj aktualnie zaznaczone obiekty Line
        selected_objs = [self.app.lines[idx] for idx in self.selected_line_indices if 0 <= idx < len(self.app.lines)]

        if not hasattr(self, '_sort_state'):
            self._sort_state = {}
        asc = not self._sort_state.get(col_id, True)
        self._sort_state[col_id] = asc

        def key_fn(idx_line):
            i, ln = idx_line
            try:
                if col_id == 'content':
                    val = ln.get_text() if hasattr(ln, 'get_text') else getattr(ln, 'text', '')
                    return (0, str(val or '').lower())
                if col_id == 'status':
                    val = getattr(ln, 'status_flag', '') or ''
                    return (0, str(val).lower())
                if col_id == 'duration':
                    val = getattr(ln, 'audio_duration', 0.0)
                    return (0, float(val if val is not None else 0.0))
                if col_id == 'similarity':
                    val = getattr(ln, 'audio_similarity', 0.0)
                    return (0, float(val if val is not None else 0.0))
                if col_id == 'cps':
                    val = ln.calculate_cps() if hasattr(ln, 'calculate_cps') else 0.0
                    if val > 0:
                        return (0, val)
                    return (1, 0.0)
                if col_id == 'audio_file':
                    val = getattr(ln, 'audio_filename', '') or ''
                    return (0, str(val).lower())
            except Exception:
                return (1, '')
            return (1, '')

        indexed = list(enumerate(self.app.lines))
        try:
            indexed.sort(key=key_fn, reverse=not asc)
        except Exception as e:
            from app.logger import Logger
            Logger.error(f"Sort failed for col {col_id}: {e}", context=f"col_id={col_id}")
            return
            
        self.app.lines = [ln for _, ln in indexed]
        
        # Przywróć zaznaczone indeksy
        new_indices = []
        # Używamy id(obj) jako unikalnego klucza dla Line, bo klasa nie jest hashable
        line_to_idx = {id(ln): idx for idx, ln in enumerate(self.app.lines)}
        for obj in selected_objs:
            obj_id = id(obj)
            if obj_id in line_to_idx:
                new_indices.append(line_to_idx[obj_id])
        
        # WAŻNE: Aktualizujemy indices i index primary
        self.selected_line_indices = new_indices
        if new_indices:
            self.app.selected_line_index = new_indices[0]
        else:
            self.app.selected_line_index = None

        self.set_preview(self.app.lines)

    def set_preview(self, lines_to_show: list[Line]):
        """
        Wypełnia tabelę danymi.
        Argument lines_to_show to lista obiektów `Line`.
        """
        if getattr(self, '_suppress_refresh', False):
            return

        # Disable updates for performance
        try:
            self.tree.grab_release()
        except: pass

        # Wyczyść tabelę
        # Faster delete for large trees
        self.tree.delete(*self.tree.get_children())
        self.item_line_map.clear()

        # --- Pre-calculation invariants ---
        view_mode = self.app.view_mode.get()
        raw_search = self.search_entry.get()
        regex_obj = None
        if raw_search:
            try:
                regex_obj = re.compile(raw_search, re.IGNORECASE)
            except re.error:
                pass

        f = self.filter_spec
        min_sim_filter = normalize_to_percent(f.get('min_sim'))
        max_sim_filter = normalize_to_percent(f.get('max_sim'))
        
        f_min_len = int(f.get('min_len')) if f.get('min_len') else None
        f_max_len = int(f.get('max_len')) if f.get('max_len') else None
        
        f_min_cps = float(f.get('min_cps')) if (f.get('min_cps') is not None and f.get('min_cps') != '') else None
        f_max_cps = float(f.get('max_cps')) if (f.get('max_cps') is not None and f.get('max_cps') != '') else None

        f_show = f.get('show')
        f_hal = f.get('halucination', 'Wszystkie')
        
        status_filter = f.get('status')
        ai_f = f.get('ai_status', 'Wszystkie')
        diff_f = f.get('diff_status', 'Wszystkie')

        # Prepare column indices once
        col_pos = {c['id']: idx for idx, c in enumerate(self.columns_config)}
        
        idx_content = col_pos.get("content")
        idx_status = col_pos.get("status")
        idx_duration = col_pos.get("duration")
        idx_char_count = col_pos.get("char_count")
        idx_cps = col_pos.get("cps")
        idx_similarity = col_pos.get("similarity")
        idx_hallucination = col_pos.get("hallucination")
        idx_format = col_pos.get("format")
        idx_audio_file = col_pos.get("audio_file")
        
        col_count = len(self.columns_config)
        
        # Audio directory pre-fetch
        app_audio_dir = getattr(self, 'app').audio_dir
        
        # --- Loop ---
        items_to_insert = []
        
        for line_obj in lines_to_show:
            if view_mode == 'Napisy':
                line_text = line_obj.get_text()
            elif view_mode == 'TTS':
                line_text = line_obj.get_tts_text()
            else:
                line_text = line_obj.original_text

            if regex_obj:
                if not regex_obj.search(line_text):
                    continue
            elif raw_search and raw_search.lower() not in line_text.lower():
                continue

            # Length Filter
            if f_min_len is not None and len(line_text) < f_min_len: continue
            if f_max_len is not None and len(line_text) > f_max_len: continue
            
            # CPS Filter
            cps_val = line_obj.calculate_cps()
            if f_min_cps is not None and cps_val < f_min_cps: continue
            if f_max_cps is not None and cps_val > f_max_cps: continue

            # similarity
            sim_val = 0.0
            has_sim = False
            if line_obj.audio_similarity is not None:
                sim_val = max(0.0, min(line_obj.audio_similarity, 1.0))
                has_sim = True
                
            # Jeśli filtr similarity jest ustawiony, pominąć linie bez weryfikacji
            if (min_sim_filter is not None or max_sim_filter is not None):
                 if not line_obj.audio_transcribed_text: # require transcription
                     continue
                 if min_sim_filter is not None and sim_val < min_sim_filter: continue
                 if max_sim_filter is not None and sim_val > max_sim_filter: continue

            # Show generated/ungenerated
            has_audio = bool(line_obj.audio_filename)
            if f_show == 'Wygenerowane' and not has_audio: continue
            elif f_show == 'Niewygenerowane' and has_audio: continue

            # Hallucination
            halo_val = line_obj.audio_hallucination
            is_pending = halo_val in ["", "PENDING"]
            has_halo = bool(halo_val and halo_val not in ["", "PENDING", "Brak"])

            if f_hal == 'Tylko halucynacje':
                if not has_halo: continue
            elif f_hal == 'Bez halucynacji':
                if is_pending or has_halo: continue
            elif f_hal == 'Nieweryfikowane':
                if not is_pending: continue
            
            # Status
            if status_filter:
                flag = getattr(line_obj, 'status_flag', None) or ""
                if status_filter == "Gotowe" and flag != "DONE": continue
                if status_filter == "Błędne" and flag != "ERROR": continue
                if status_filter == "Bez flagi" and flag != "": continue

            # Filter by SI Processed flag
            is_ai = getattr(line_obj, 'ai_processed', False)
            if ai_f == 'Tak' and not is_ai: continue
            if ai_f == 'Nie' and is_ai: continue

            # Filter by Diff (Text vs TTS)
            if diff_f != 'Wszystkie':
                t_val = line_obj.get_text()
                tts_val = line_obj.get_tts_text()
                # Compare actual values
                is_diff = (t_val != tts_val)
                if diff_f == 'Tylko zmienione' and not is_diff: continue
                if diff_f == 'Bez zmian' and is_diff: continue

            # --- Row Building ---
            row_values = [""] * col_count

            if idx_content is not None:
                row_values[idx_content] = line_text

            if idx_char_count is not None:
                if view_mode == 'Napisy':
                    char_val = len(line_obj.get_text())
                elif view_mode == 'TTS':
                    char_val = len(line_obj.get_tts_text())
                else:
                    char_val = len(line_obj.original_text)
                row_values[idx_char_count] = str(char_val)

            if idx_status is not None:
                flag = getattr(line_obj, 'status_flag', None)
                if flag == "DONE": row_values[idx_status] = "Gotowe"
                elif flag == "ERROR": row_values[idx_status] = "Błąd"

            if idx_duration is not None:
                duration_val = line_obj.audio_duration
                row_values[idx_duration] = f"{duration_val:.2f}" if duration_val > 0 else '-'
            
            if idx_cps is not None:
                row_values[idx_cps] = f"{cps_val:.1f}" if (cps_val and cps_val > 0) else '-'
            
            if idx_similarity is not None:
                sim_display = format_percent(sim_val) if has_sim else '-'
                row_values[idx_similarity] = sim_display
            
            if idx_hallucination is not None:
                if halo_val and halo_val != "PENDING":
                    row_values[idx_hallucination] = halo_val
                elif halo_val == "PENDING":
                    row_values[idx_hallucination] = "?"
                elif line_obj.audio_status:
                    row_values[idx_hallucination] = "Brak"
                else:
                    row_values[idx_hallucination] = "-"

            if idx_format is not None:
                fmt = line_obj.audio_format
                row_values[idx_format] = (fmt or '').upper()
                
            if idx_audio_file is not None:
                # Optimized audio path logic - avoid Disk IO
                fname = line_obj.audio_filename
                if fname:
                    # Trust metadata if present
                    row_values[idx_audio_file] = fname
                else:
                    # Only calculate/guess if missing (slow path)
                    # We can even skip this if performance is critical
                    # or cache it. For now, let's keep it minimal.
                    # line_obj.uid check is fast
                    if line_obj.uid:
                         # Heuristic display without disk check or minimize it
                         row_values[idx_audio_file] = "Brak pliku"
                    else:
                         row_values[idx_audio_file] = ""

            # insert directly
            item_id = self.tree.insert("", "end", values=tuple(row_values))
            self.item_line_map[item_id] = line_obj
            
        # przywracamy je w nowej tabeli JEŚLI wiersze są dostępne
        if self.selected_line_indices:
            items_to_select = []
            # Używamy UID jako klucza, bo klasa Line nie jest hashable (dataclass)
            uid_to_item = {getattr(obj, 'uid', id(obj)): iid for iid, obj in self.item_line_map.items()}
            for idx in self.selected_line_indices:
                if 0 <= idx < len(self.app.lines):
                    line_obj = self.app.lines[idx]
                    l_uid = getattr(line_obj, 'uid', id(line_obj))
                    if l_uid in uid_to_item:
                        items_to_select.append(uid_to_item[l_uid])
            if items_to_select:
                self.tree.selection_set(*items_to_select)
                self.tree.see(items_to_select[0])
                # Synchronizuj selected_line_indices z faktycznym stanem tabeli
                self.on_tree_select(None)
            else:
                self.app.selected_line_index = None
                self.selected_line_indices = []
                self.update_audio_buttons_state()
        else:
            self.app.selected_line_index = None
            self.selected_line_indices = []
            self.update_audio_buttons_state()

    def on_tree_select(self, event):
        """Obsługa wyboru wiersza w tabeli - aktualizuje selected_line_indices."""
        selected_items = self.tree.selection()
        
        if not selected_items:
            self.app.selected_line_index = None
            self.selected_line_indices = []
            self.update_audio_buttons_state()
            return

        # Pobierz wszystkie zaznaczone elementy
        selected_indices = []
        for item_id in selected_items:
            line_obj = self.item_line_map.get(item_id)
            if line_obj:
                try:
                    idx = self.app.lines.index(line_obj)
                    selected_indices.append(idx)
                except ValueError:
                    continue

        # Ustaw first selected jako primary
        if selected_indices:
            self.app.selected_line_index = selected_indices[0]
            self.selected_line_indices = selected_indices
        else:
            self.app.selected_line_index = None
            self.selected_line_indices = []

        self.update_audio_buttons_state()

    def select_all_visible(self, event=None):
        """Zaznacza wszystkie widoczne wiersze (limit 100)."""
        items = self.tree.get_children()
        if not items:
            return "break"

        limit = 100
        to_select = items[:limit]

        self.tree.selection_set(*to_select)
        if to_select:
            self.tree.see(to_select[0])

        self.on_tree_select(None)
        return "break"

    def _start_inline_edit(self, event):

        """Uruchamia edycję inline tekstu w tabeli."""
        # Sprawdzenie czy jesteśmy w edytowalnym trybie
        mode = self.app.view_mode.get()
        if mode == "Oryginał":
            return
        
        # Jeśli wywołane klawiszem (np. F2), weź aktualnie zaznaczony element
        if event.type == tk.EventType.KeyPress:
            selected = self.tree.selection()
            if not selected:
                return
            item = selected[0]
            # Znajdź indeks kolumny "content"
            col_id = "content"
            col_idx = 0
            for i, config in enumerate(self.columns_config):
                if config["id"] == "content":
                    col_idx = i
                    break
        else:
            # Kliknięcie myszą (Alt+Btn1)
            item = self.tree.identify_row(event.y)
            col = self.tree.identify_column(event.x)
            
            if not item or not col:
                return
            
            # Pobierz indeks kolumny (np. '#1' -> 0)
            try:
                col_idx = int(col[1:]) - 1
            except (ValueError, IndexError):
                return
            
            if col_idx < 0 or col_idx >= len(self.columns_config):
                return
            col_id = self.columns_config[col_idx]["id"]

        if col_id != "content":
            return
        
        # Upewnij się, że wiersz jest zaznaczony przed edycją
        if item not in self.tree.selection():
            self.tree.selection_set(item)
            self.on_tree_select(None)

        # Pobierz obiekt linii i jej indeks
        line_obj = self.item_line_map.get(item)
        if not line_obj:
            return
            
        # Blokada ręcznej edycji dla linii oznaczonych jako gotowe
        if getattr(line_obj, 'status_flag', None) == "DONE":
            return

        try:
            line_idx = self.app.lines.index(line_obj)
        except ValueError:
            return
            
        # Pobierz aktualny tekst z konfiguracji kolumn
        item_values = self.tree.item(item, "values")
        try:
            current_text = item_values[col_idx] or ""
        except IndexError:
            current_text = ""
        
        # Zaznacz wiersz
        self.tree.selection_set(item)
        self.app.selected_line_index = line_idx
        
        # Utwórz entry widget dla edycji inline
        self._create_inline_editor(item, col_idx, current_text, line_idx)

    def _create_inline_editor(self, item_id, col_idx, current_text, line_idx):
        """Tworzy entry widget dla edycji inline."""
        # Jeśli już jest edytor, go usuniesz
        if self.inline_edit_entry:
            self.inline_edit_entry.destroy()
            self.inline_edit_entry = None
        
        # Pobierz bbox komórki
        x, y, width, height = self.tree.bbox(item_id, column=col_idx)
        if x is None:
            return
        
        # Utwórz entry widget nad komórką
        self.inline_edit_entry = tk.Entry(self.tree, font=("Arial", 12), width=int(width / 8))
        self.inline_edit_entry.insert(0, current_text)
        self.inline_edit_entry.place(x=x, y=y, width=width, height=height)
        
        # Ustaw fokus i zaznacz tekst
        self.inline_edit_entry.focus()
        self.inline_edit_entry.select_range(0, tk.END)
        
        # Przechowaj dane o edycji
        self.inline_edit_item = (item_id, col_idx, line_idx)
        
        # Bind zdarzeń
        self.inline_edit_entry.bind("<Return>", self._save_inline_edit)
        self.inline_edit_entry.bind("<Escape>", self._cancel_inline_edit)
        self.inline_edit_entry.bind("<FocusOut>", self._save_inline_edit)

    def _save_inline_edit(self, event=None):
        """Zapisuje zmianę edycji inline bezpośrednio do CSV."""
        if not self.inline_edit_entry or not self.inline_edit_item:
            return
        
        item_id, col_idx, line_idx = self.inline_edit_item
        
        # Check if item still exists in tree (might have been removed or filtered out)
        if not self.tree.exists(item_id):
            self.inline_edit_entry.destroy()
            self.inline_edit_entry = None
            self.inline_edit_item = None
            return

        new_text = self.inline_edit_entry.get()
        
        # Usuń entry widget
        self.inline_edit_entry.destroy()
        self.inline_edit_entry = None
        self.inline_edit_item = None
        
        # Zaktualizuj bezpośrednio w app.lines (nie w manual_edits/tts_edits)
        mode = self.app.view_mode.get()
        # Use setters! This ensures correct behavior (setting to None if equals parent value)
        if mode == "Napisy":
            self.app.lines[line_idx].set_text(new_text)
        elif mode == "TTS":
            self.app.lines[line_idx].set_tts_text(new_text)
        
        # Zapisz do CSV bezpośrednio
        try:
            if self.app.loaded_path:
                update_line_in_csv(self.app.lines[line_idx], str(self.app.loaded_path))
        except Exception as e:
            from app.logger import Logger
            Logger.error(f"Błąd zapisu do CSV: {e}")
        
        # Odśwież UI pojedynczego wiersza (Optymalizacja)
        values = list(self.tree.item(item_id, "values"))
        col_pos = {c['id']: idx for idx, c in enumerate(self.columns_config)}
        if "content" in col_pos:
            values[col_pos["content"]] = new_text
        
        self.tree.item(item_id, values=values)
        
        # apply_patterns(self.app)  <-- To powodowało pełne odświeżenie (wolne!)
        # self.set_preview(self.app.lines) <-- To powodowało pełne przerysowanie (wolne!)

    def _cancel_inline_edit(self, event=None):
        """Anuluje edycję inline bez zmian."""
        if self.inline_edit_entry:
            self.inline_edit_entry.destroy()
            self.inline_edit_entry = None
            self.inline_edit_item = None

    def _show_context_menu(self, event):
        item_id = self.tree.identify_row(event.y)
        if item_id:
            self.tree.selection_set(item_id)
            # Force update of selection state immediately, because selection_set
            # does not always trigger <<TreeviewSelect>> immediately or at all in some conditions
            self.on_tree_select(None)

        if not self.tree.selection() or self.app.selected_line_index is None:
            return

        menu = tk.Menu(self, tearoff=0)
        can_gen = self.generate_button.cget("state") == "normal"
        can_verify = self.verify_button.cget("state") == "normal"
        can_del = self.delete_all_button.cget("state") == "normal"
        can_edit = self.app.view_mode.get() != "Oryginał"

        menu.add_command(label="⚙️ Generuj audio (Ctrl+G)", command=self.generate_selected_dialogs,
                         state=tk.NORMAL if can_gen else tk.DISABLED)
        menu.add_command(label="✓ Weryfikuj audio (Ctrl+V)", command=self.verify_selected_dialogs,
                         state=tk.NORMAL if can_verify else tk.DISABLED)
        menu.add_command(label="✨ Zadania SI (Ctrl+Alt+A)", command=self.open_ai_runner_selected,
                         state=tk.NORMAL)
        menu.add_command(label="🗑️ Usuń audio (Ctrl+X)", command=self.delete_selected_dialogs,
                         state=tk.NORMAL if can_del else tk.DISABLED)
        menu.add_command(label="🗑️ Usuń zaznaczone wiersze", command=self.delete_selected_rows,
                         state=tk.NORMAL)
        menu.add_separator()
        menu.add_command(label="↺ Przywróć wartość", command=self.restore_selected_values, state=tk.NORMAL)
        menu.add_separator()
        menu.add_command(label="✅ Oznacz jako Gotowe", command=lambda: self.set_selected_status("DONE"), state=tk.NORMAL)
        menu.add_command(label="⚠️ Oznacz jako Błędne", command=lambda: self.set_selected_status("ERROR"), state=tk.NORMAL)
        menu.add_command(label="⚪ Wyczyść flagi", command=lambda: self.set_selected_status(None), state=tk.NORMAL)
        menu.add_separator()
        menu.add_command(label="📄 Kopiuj linię (Ctrl+C)", command=lambda: self.app._on_ctrl_c_from_menu(),
                         state=tk.NORMAL)
        menu.add_separator()
        menu.add_command(label="➕ Dodaj wzorzec zamieniający (Ctrl+Klik)",
                         command=lambda: add_replace_pattern_from_selection(self.app, from_menu=True), state=tk.NORMAL)

        menu.tk_popup(event.x_root, event.y_root)

    def set_selected_status(self, status: Optional[str]):
        """Ustawia flagę statusu dla zaznaczonych wierszy."""
        if not self.selected_line_indices:
            return
            
        changed = False
        to_update = []
        for idx in self.selected_line_indices:
            if 0 <= idx < len(self.app.lines):
                line = self.app.lines[idx]
                
                # Check if change is needed
                current = getattr(line, 'status_flag', None) or None
                target = status or None
                if current != target:
                    line.status_flag = status
                    to_update.append(line)
                    changed = True
        
        if changed and to_update:
            try:
                # Use bulk update
                update_lines_in_csv(to_update, str(self.app.loaded_path))
                self.set_preview(self.app.lines)
            except Exception as e:
                from app.logger import Logger
                Logger.error(f"Error saving status: {e}")

    def restore_selected_values(self):
        """
        Przywraca wartości dla zaznaczonych wierszy zależnie od widoku:
        - Widok TTS: przywraca wartość z pola Text.
        - Widok Text/Napisy: przywraca wartość z Oryginału.
        """
        if not self.selected_line_indices:
            return

        mode = self.app.view_mode.get()
        if mode == "Oryginał":
            messagebox.showinfo("Info", "Nie można przywracać w widoku Oryginału.", parent=self)
            return

        to_update = []
        changed = False
        
        for idx in self.selected_line_indices:
             if 0 <= idx < len(self.app.lines):
                line = self.app.lines[idx]
                
                # Check status
                if getattr(line, 'status_flag', None) == "DONE":
                    continue

                if mode == "TTS":
                    # Restore TTS from Text
                    # We want effective TTS to be result of effective Text
                    target_val = line.get_text()
                    
                    # Determine if update is needed:
                    # 1. Effective values differ (visual change)
                    # 2. OR explicit override exists (data cleanup)
                    if line.get_tts_text() != target_val or line.tts_text is not None:
                         line.set_tts_text(target_val) # Will set tts_text = None
                         to_update.append(line)
                         changed = True

                elif mode == "Napisy": # Text View
                    # Restore Text from Original
                    target_val = line.original_text
                    
                    if line.get_text() != target_val or line.text is not None:
                        line.set_text(target_val) # Will set text = None
                        line.ai_processed = False # Reset flag on full restore
                        to_update.append(line)
                        changed = True
        
        if changed and to_update:
            try:
                update_lines_in_csv(to_update, str(self.app.loaded_path))
                self.set_preview(self.app.lines)
                self.app.set_status(f"Przywrócono wartości dla {len(to_update)} wierszy.")
            except Exception as e:
                messagebox.showerror("Błąd", f"Nie udało się zapisać zmian: {e}", parent=self)
        else:
            self.app.set_status("Brak zmian do wykonania.")

    # --- Weryfikacja audio (zintegrowana) ---
    def start_verification(self, force_refresh=False, ignore_short=True, verify_options=None):
        """Uruchamia proces weryfikacji audio."""
        if verify_options is None:
            verify_options = {}

        if not self.app.audio_dir:
            messagebox.showwarning("Brak audio", "Najpierw wybierz katalog audio.", parent=self)
            return
        if not self.app.lines:
            messagebox.showwarning("Brak tekstu", "Brak napisów do weryfikacji.", parent=self)
            return

        if self.ver_running:
            return

        self.ver_running = True
        self.ver_stop_event.clear()
        self.ver_processed_count = 0  # Reset counter

        try:
            cpu_count = os.cpu_count() or 4
        except Exception:
            cpu_count = 4
        try:
            workers_cfg = int(self.app.global_config.get('verification_workers', self.app.global_config.get('conversion_workers', max(1, cpu_count // 2))))
        except Exception:
            workers_cfg = max(1, cpu_count // 2)
        workers = max(1, min(workers_cfg, cpu_count * 2))

        line_uids = [getattr(l, 'uid', str(i + 1)) for i, l in enumerate(self.app.lines)]
        audio_dir = str(self.app.audio_dir)
        ffprobe = shutil.which('ffprobe')

        if VerificationManager is None:
            messagebox.showerror("Błąd", "Brak VerificationManager.", parent=self)
            self.ver_running = False
            return

        manager = VerificationManager.get_instance()

        def apply_cb(results: dict):
            try:
                self.after(0, lambda r=results: self._apply_verification_results(r))
            except Exception:
                pass

        job = VerificationJob(
            project_path=str(getattr(self.app, 'current_project_path', '')),
            audio_dir=audio_dir,
            lines=self.app.lines,
            line_uids=line_uids,
            force_refresh=force_refresh,
            ignore_short=ignore_short,
            ffprobe=ffprobe,
            workers=8,
            verify_hallucination=verify_options.get('verify_hallucination', False),
            verify_similarity=verify_options.get('verify_similarity', False),
            apply_callback=apply_cb
        )

        manager.add_job(job)
        try:
            self.after(0, lambda: self.app.set_status("Weryfikacja uruchomiona"))
        except Exception:
            pass
        return

    def _refresh_verification_view(self):
        """Odświeża widok weryfikacji dla zaznaczonych wierszy."""
        uid_to_item = {getattr(ln, 'uid', id(ln)): iid for iid, ln in self.item_line_map.items()}
        col_pos = {c['id']: idx for idx, c in enumerate(self.columns_config)}
        
        updated_count = 0
        for line_idx in self.selected_line_indices:
            if 0 <= line_idx < len(self.app.lines):
                line_obj = self.app.lines[line_idx]
                item_id = uid_to_item.get(getattr(line_obj, 'uid', id(line_obj)))
                if not item_id:
                    continue
                
                row_values = list(self.tree.item(item_id, "values"))
                
                try:
                    if 'duration' in col_pos:
                        duration_val = float(getattr(line_obj, 'audio_duration', 0.0) or 0.0)
                        row_values[col_pos['duration']] = f"{duration_val:.2f}" if duration_val > 0 else '-'
                    
                    if 'cps' in col_pos:
                        try:
                            txt_source = line_obj.get_tts_text() if hasattr(line_obj, 'get_tts_text') else getattr(line_obj, 'tts_text', '')
                            txt = (txt_source or '').strip('.?!')
                            from collections import Counter
                            stats = Counter(txt)
                            short = stats[','] + stats['-']
                            long = stats['.'] + stats['!'] + stats['?']
                            pauses = (short * 0.4) + (long * 0.6)
                            duration = float(getattr(line_obj, 'audio_duration', 0.0) or 0.0)
                            cps_val = len(txt) / (duration - pauses) if (duration - pauses) > 0 else 0.0
                        except Exception:
                            cps_val = 0.0
                        row_values[col_pos['cps']] = f"{cps_val:.1f}" if (cps_val and cps_val > 0) else '-'
                    
                    if 'similarity' in col_pos:
                        similarity_val = float(getattr(line_obj, 'audio_similarity', 0.0) or 0.0)
                        sim_display = format_percent(similarity_val)
                        row_values[col_pos['similarity']] = sim_display if sim_display else '-'
                    
                    if 'format' in col_pos:
                        fmt = (getattr(line_obj, 'audio_format', '') or '')
                        row_values[col_pos['format']] = (fmt or '').upper()
                    
                    if 'audio_file' in col_pos:
                        path = None
                        if getattr(line_obj, 'audio_filename', ''):
                            path = str(Path(getattr(self, 'app').audio_dir or Path('.')) / line_obj.audio_filename)
                        row_values[col_pos['audio_file']] = Path(path).name if path else ''
                    
                    self.tree.item(item_id, values=tuple(row_values))
                    updated_count += 1
                except Exception:
                    pass
    
    def _apply_verification_results(self, data: dict):
        """
        Apply merged verification results (called on main thread).
        `data` is a dict mapping string id -> entry dict produced by worker.
        """
        from app.io import update_lines_in_csv

        any_changes = False
        batch_processed_count = 0
        
        for k, v in data.items():
            if k == '__done':
                continue
            
            if not isinstance(v, dict):
                continue
                
            batch_processed_count += 1
            
            # Check if line was modified
            is_modified = v.get('__modified', True)
            
            if not is_modified:
                continue

            try:
                line = None
                uid = v.get('uid')
                uid_map = getattr(self, 'ver_uid_map', None)
                
                if uid and uid_map:
                    line = uid_map.get(uid)
                
                if not line:
                    try:
                        idx = int(k) - 1
                        if idx >= 0 and idx < len(self.app.lines):
                            line = self.app.lines[idx]
                    except ValueError:
                        pass
                
                if not line:
                    continue
                
                # Aktualizacja pól obiektu Line z danych otrzymanych od pracownika
                line.audio_duration = v.get('audio_duration', line.audio_duration)
                line.audio_status = v.get('audio_status', line.audio_status)
                line.audio_similarity = v.get('audio_similarity', line.audio_similarity)
                line.audio_transcribed_text = v.get('audio_transcribed_text', line.audio_transcribed_text)
                line.audio_hallucination = v.get('audio_hallucination', line.audio_hallucination)
                line.audio_filename = v.get('audio_filename', line.audio_filename)
                line.audio_format = v.get('audio_format', line.audio_format)

                # Dodaj do bufora zapisu
                self.ver_modified_buffer.append(line)
                any_changes = True

                # Jeśli bufor przekroczył 100 LUB minęło 10 sekund, zapisz do CSV
                should_save = len(self.ver_modified_buffer) >= 100
                if not should_save and self.ver_modified_buffer:
                    if time.time() - getattr(self, 'ver_last_save_time', 0) > 10:
                        should_save = True

                if should_save:
                    try:
                        update_lines_in_csv(self.ver_modified_buffer)
                        self.ver_modified_buffer = []
                        self.ver_last_save_time = time.time()
                    except Exception:
                        pass

            except Exception as e:
                from app.logger import Logger
                Logger.error(f"[VERIFY_APPLY_ERROR] {e}")
                continue
        
        # Aktualizacja licznika postępu
        if hasattr(self, 'ver_processed_count'):
            self.ver_processed_count += batch_processed_count
        else:
            self.ver_processed_count = batch_processed_count

        # handle special flags
        if '__done' in data or data.get('__done') is True:
            # Finalny zapis bufora
            if self.ver_modified_buffer:
                try:
                    update_lines_in_csv(self.ver_modified_buffer)
                except Exception:
                    pass
                self.ver_modified_buffer = []

            self.ver_running = False
            if hasattr(self, 'ver_uid_map'):
                self.ver_uid_map = None
            if hasattr(self, 'ver_uid_to_index_map'):
                self.ver_uid_to_index_map = None

            try:
                self.after(0, lambda: self.app.set_status('Weryfikacja zakończona'))
            except Exception:
                pass

        if any_changes:
            # Odśwież widok częściowo (szukamy właściwych indeksów wierszy w UI poprzez UID)
            try:
                indices_to_refresh = []
                
                # Słownik: uid -> modified_flag
                modified_uids = []
                for k, v in data.items():
                    if k == '__done': continue
                    if v.get('__modified', True):
                        u = v.get('uid')
                        if u:
                             modified_uids.append(u)
                
                if modified_uids and hasattr(self, 'ver_uid_to_index_map') and self.ver_uid_to_index_map:
                    for u in modified_uids:
                        idx = self.ver_uid_to_index_map.get(u)
                        if idx is not None:
                            indices_to_refresh.append(idx)
                
                # Fallback jeśli mapy brak (np. pełna weryfikacja), wtedy k jest indeksem + 1
                if not indices_to_refresh and not modified_uids:
                     for k, v in data.items():
                        if k == '__done': continue
                        if not v.get('__modified', True): continue
                        try:
                            indices_to_refresh.append(int(k) - 1)
                        except: pass

                if indices_to_refresh:
                    self._refresh_lines_view(indices_to_refresh)
                
            except Exception as e:
                from app.logger import Logger
                Logger.error(f"[APPLY_RESULTS] BŁĄD w odświeżaniu widoku: {e}")

    def _refresh_lines_view(self, indices: List[int]):
        """Szybkie odświeżenie widoku (tylko kolumn weryfikacji) dla podanych indeksów."""
        # Mapowanie obiektów na item_id
        # self.item_line_map: item_iid -> Line
        # Ale my potrzebujemy odwrotnie: Line -> item_iid
        # Możemy zbudować mapę odwrotną, ale to kosztowne jeśli robione często.
        # Może lepiej trzymać ją jako field?
        
        # Na razie zbudujmy dla bezpieczeństwa, jeśli lista jest ogromna to i tak set_preview by mulił.
        line_to_item = {id(line): iid for iid, line in self.item_line_map.items()}
        
        col_pos = {c['id']: idx for idx, c in enumerate(self.columns_config)}
        
        for idx in indices:
            if idx < 0 or idx >= len(self.app.lines):
                continue
            line = self.app.lines[idx]
            item_id = line_to_item.get(id(line))
            if not item_id:
                # Może linia nie jest widoczna (np. filtr)?
                continue
            
            # Pobierz obecne wartości
            try:
                values = list(self.tree.item(item_id, "values"))
            except:
                continue
                
            # Zaktualizuj tylko te kolumny które zależą od weryfikacji
            # Duration, Status (raw/display?), CPS, Similarity, Audio File
            
            # ... (logika podobna do _refresh_verification_view ale generyczna)
            
            if 'duration' in col_pos:
                duration_val = float(getattr(line, 'audio_duration', 0.0) or 0.0)
                values[col_pos['duration']] = f"{duration_val:.2f}" if duration_val > 0 else '-'

            if 'status' in col_pos:
                 # Tutaj logika statusu - przyjmijmy prosto
                 st = getattr(line, 'audio_status', '')
                 values[col_pos['status']] = st

            if 'cps' in col_pos:
                # Przelicz CPS
                try:
                     txt = line.get_tts_text().strip()
                     from collections import Counter
                     stats = Counter(txt)
                     pauses = (stats[','] + stats['-']) * 0.4 + (stats['.'] + stats['!'] + stats['?']) * 0.6
                     dur = float(getattr(line, 'audio_duration', 0.0) or 0.0)
                     eff_dur = dur - pauses
                     cps = len(txt) / eff_dur if eff_dur > 0 else 0.0
                     values[col_pos['cps']] = f"{cps:.1f}" if cps > 0 else '-'
                except:
                     values[col_pos['cps']] = '-'

            if 'similarity' in col_pos:
                sim = float(getattr(line, 'audio_similarity', 0.0) or 0.0)
                # Helper format_percent jest gdzieś globalnie? Użyjmy prostego
                sim_display = f"{int(sim*100)}%" if sim > 0 else '-'
                values[col_pos['similarity']] = sim_display
            
            if 'hallucination' in col_pos:
                 hal = getattr(line, 'audio_hallucination', '')
                 values[col_pos['hallucination']] = hal if hal else '-'

            self.tree.item(item_id, values=values)

    # --- Weryfikacja audio (stara) ---

    def stop_verification(self):
        """Stop currently running verification via manager"""
        try:
            from audio.verification_manager import VerificationManager
            VerificationManager.get_instance().cancel_current()
        except Exception:
            pass
        self.ver_running = False
        self.ver_stop_event.set()
        

    def open_verification_folder(self):
        # Open folder for selected item or audio_dir
        sel = self.tree.selection()
        path = self.app.audio_dir
        
        if sel:
            item_id = sel[0]
            line_obj = self.item_line_map.get(item_id)
            if line_obj and line_obj.audio_filename:
                path = (Path(self.app.audio_dir) / line_obj.audio_filename).parent
        
        if not path:
            return

        if os.name == 'nt':
            os.startfile(path)
        else:
            subprocess.call(['xdg-open', str(path)])

    def _get_line_text(self, idx):
        try:
            mode = self.app.view_mode.get()
            line = self.app.lines[idx]
            line_text = line.get_text() if hasattr(line, 'get_text') else (line.text or '')
            if mode == 'Napisy':
                return line_text
            elif mode == 'TTS':
                return line.tts_text or ''
            else:
                return line_text
        except Exception:
            return ''

    def open_filter_window(self):
        try:
            from ui.filter_window import FilterWindow
        except Exception:
            return
        FilterWindow(self, current_filters=getattr(self, 'filter_spec', {}), apply_callback=self._on_filter_apply)

    def _on_filter_apply(self, filters: dict = {}):
        # store filters and refresh view
        self.filter_spec = filters or {}
        try:
            self.set_preview(self.app.lines)
        except Exception as e:
            from app.logger import Logger
            Logger.error(f"Błąd podczas stosowania filtrów: {e}")

    def update_audio_buttons_state(self):
        """Aktualizuje stan przycisków w oparciu o zaznaczenie."""
        has_selection = len(self.selected_line_indices) > 0
        state = "normal" if has_selection else "disabled"
        
        self.generate_button.configure(state=state)
        self.verify_button.configure(state=state)
        self.delete_all_button.configure(state=state)

        status_msg = "Audio: ---"
        if has_selection and self.app.audio_dir and self.app.audio_dir.is_dir():
            # Sprawdz pierwszy zaznaczony
            try:
                selected_line = self.app.lines[self.app.selected_line_index]
                
                # Szukanie wyłącznie po UID (standardowa konwencja)
                uid = getattr(selected_line, 'uid', None)
                found_files = []
                if uid:
                    found_files = get_audio_candidates(uid)

                if found_files:
                    status_msg = f"Audio: znaleziono {len(found_files)}"
                    self.first_found_audio = found_files[0][0]
                else:
                    status_msg = "Audio: brak"
                    self.first_found_audio = None
            except (IndexError, TypeError):
                self.first_found_audio = None

        # Aktualizacja statusu
        if hasattr(self.app, 'set_audio_status'):
            self.app.set_audio_status(status_msg)

    def stop_audio(self):
        if self.current_audio_process:
            try:
                self.current_audio_process.terminate()
                self.current_audio_process = None
            except Exception:
                self.current_audio_process = None

    def play_selected_audio(self, event=None):
        if not FFPLAY_AVAILABLE or not self.app.audio_dir:
            return

        item_id = None
        # Jeśli wywołane klawiszem (np. spacją), ignoruj pozycję myszy
        if event is not None and event.type != tk.EventType.KeyPress:
            try:
                # identifies the row under the mouse cursor
                item_id = self.tree.identify_row(event.y)
            except Exception:
                item_id = None

        if not item_id:
            selected_items = self.tree.selection()
            if selected_items:
                item_id = selected_items[0]

        if not item_id:
            return

        line_obj = self.item_line_map.get(item_id)
        if line_obj is None and self.app.selected_line_index is not None:
            try:
                line_obj = self.app.lines[self.app.selected_line_index]
            except Exception:
                line_obj = None

        if not line_obj:
            return

        # Logika wyszukiwania pliku - oparta wyłącznie na UID
        file_to_play = None
        identifier = line_obj.uid
        
        file_to_play, _ = VerificationManager._find_audio_for_uid(identifier)

        if not file_to_play:
            return

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

    def get_selected_lines(self) -> List[Line]:
        """Zwraca listę zaznaczonych obiektów Line."""
        if not self.selected_line_indices:
            return []
        
        selected = []
        for idx in self.selected_line_indices:
             if idx < len(self.app.lines):
                 selected.append(self.app.lines[idx])
        return selected

    def open_ai_runner_selected(self):
        """Otwiera okno zadań AI dla zaznaczonych wierszy."""
        try:
            from ui.ai_runner import AITaskRunnerWindow
            
            selected = self.get_selected_lines()
            if not selected:
                 # Try to use current selection index if get_selected_lines fails or is empty for single selection
                 if self.selected_line_indices:
                     selected = [self.app.lines[i] for i in self.selected_line_indices if i < len(self.app.lines)]
            
            if not selected:
                 messagebox.showwarning("Brak zaznaczenia", "Zaznacz wiersze w edytorze.", parent=self.app)
                 return

            AITaskRunnerWindow(self.app, selected, is_global=False)
        except Exception as e:
            messagebox.showerror("Błąd", f"Nie można otworzyć okna zadań AI: {e}", parent=self.app)
            from app.logger import Logger
            Logger.error(f"Error opening AI runner: {e}")


    def generate_selected_dialogs(self):

        """Generuje audio dla wszystkich zaznaczonych wierszy."""
        if not self.selected_line_indices or not self.app.audio_dir:
            return

        lines_to_gen = []
        skipped_done = 0
        
        for idx in self.selected_line_indices:
            try:
                line_no = idx + 1
                line_obj = self.app.lines[idx]
                
                # Zabezpieczenie przed generowaniem "Gotowych" wierszy
                if getattr(line_obj, 'status_flag', None) == "DONE":
                    skipped_done += 1
                    continue
                
                getter = getattr(line_obj, 'get_tts_text', None)
                candidate = getter() if callable(getter) else getattr(line_obj, 'tts_text', '')
                text = (candidate or '').strip()
                if not text:
                    continue
                uid = getattr(line_obj, 'uid', str(line_no))
                lines_to_gen.append((uid, text))
            except (IndexError, ValueError):
                continue
                
        if skipped_done > 0:
             if not lines_to_gen:
                 messagebox.showinfo("Informacja", f"Pominięto {skipped_done} wierszy oznaczonych jako 'Gotowe'. Brak innych wierszy do wygenerowania.")
                 return
             else:
                 # Opcjonalnie można wyświetlić info, ale może być irytujące
                 pass

        if not lines_to_gen:
            messagebox.showwarning("Brak danych", "Nie można wygenerować audio dla zaznaczonych linii.", parent=self)
            return

        tts_model = get_active_tts_model_name(self.app)
        if not tts_model:
            messagebox.showerror("Błąd", "Brak modelu TTS.", parent=self)
            return

        from audio.generation_manager import GenerationManager, GenerationJob
        job = GenerationJob(
            project_path=f"ZAZNACZONYCH ({len(lines_to_gen)}) - {self.app.current_project_path.name}",
            audio_dir=self.app.audio_dir,
            lines_to_generate=lines_to_gen,
            tts_model_name=tts_model,
            tts_config=gather_tts_config(self.app),
            converter_config=gather_converter_config(self.app)
        )

        uid_to_idx = {getattr(self.app.lines[i], 'uid', ''): i for i in range(len(self.app.lines))}

        def _on_generate(identifier: str, path: str):
            try:
                idx = uid_to_idx.get(identifier)
                if idx is None:
                    idx = next((i for i, l in enumerate(self.app.lines) if getattr(l, 'uid', '') == identifier), None)
                if idx is not None and 0 <= idx < len(self.app.lines):
                    self.app.lines[idx].audio_filename = Path(path).name
                    self.app.lines[idx].audio_status = 'OK'
                    
                    # Reset verification flags
                    self.app.lines[idx].audio_similarity = 0.0
                    self.app.lines[idx].audio_hallucination = "PENDING"

                    try:
                        from app.io import save_lines_to_file
                        if getattr(self.app, 'loaded_path', None):
                            save_lines_to_file(str(self.app.loaded_path), self.app.lines)
                    except Exception:
                        pass
            except Exception:
                pass

        job.on_generate = _on_generate
        GenerationManager.get_instance().add_job(job)
        self.app.set_status(f"Dodano zadanie ({len(lines_to_gen)} linii) do kolejki.")

    def verify_selected_dialogs(self):
        """Weryfikuje audio dla wszystkich zaznaczonych wierszy w osobnym wątku."""
        try:
            from audio.verification_manager import VerificationManager, VerificationJob

            if not self.selected_line_indices:
                messagebox.showwarning("Weryfikacja", "Nie wybrano żadnych wierszy.", parent=self)
                return

            if not self.app.audio_dir:
                 messagebox.showwarning("Weryfikacja", "Brak ustawionego katalogu audio.", parent=self)
                 return

            # Add to queue even if another verification is running
            was_running = self.ver_running
            self.ver_running = True
            
            if not was_running:
                self.ver_processed_count = 0
                self.ver_last_save_time = time.time()
                self.ver_uid_map = {}
                self.ver_uid_to_index_map = {}
            
            # Map UIDs for UI updates
            try:
                new_uid_map = {l.uid: l for l in self.app.lines if hasattr(l, 'uid')}
                new_uid_to_idx = {}
                for i, l in enumerate(self.app.lines):
                    uid = getattr(l, 'uid', None)
                    if uid:
                        new_uid_to_idx[uid] = i
                
                self.ver_uid_map = new_uid_map
                self.ver_uid_to_index_map = new_uid_to_idx
                
            except Exception as e:
                from app.logger import Logger
                Logger.error(f"[VERIFY_INIT_ERROR] Map creation failed: {e}")
                
            if not was_running:
                self.app.set_status(f"Weryfikacja {len(self.selected_line_indices)} linii...")
            else:
                 self.app.set_status(f"Dodano do kolejki ({len(self.selected_line_indices)} linii)...")

            # Prepare subset
            subset_lines = []
            subset_uids = []
            for idx in self.selected_line_indices:
                if idx < 0 or idx >= len(self.app.lines):
                    continue
                line = self.app.lines[idx]
                subset_lines.append(line)
                subset_uids.append(getattr(line, 'uid', str(idx + 1)))

            ffprobe = shutil.which('ffprobe')
            
            def apply_cb(results: dict):
                try:
                    self.after(0, lambda r=results: self._apply_verification_results(r))
                except Exception:
                    pass

            manager = VerificationManager.get_instance()
            
            job = VerificationJob(
                project_path=str(getattr(self.app, 'current_project_path', '')),
                audio_dir=str(self.app.audio_dir),
                lines=subset_lines,
                line_uids=subset_uids,
                force_refresh=True,
                ignore_short=True,
                ffprobe=ffprobe,
                workers=4,
                verify_hallucination=True,  # Zgodnie z żądaniem: Hallucinations + CPS
                verify_similarity=False,    # Zgodnie z żądaniem: No Similarity
                apply_callback=apply_cb
            )
            
            manager.add_job(job, priority=0)
            
        except Exception as e:
            self.ver_running = False
            import traceback
            traceback.print_exc()
            messagebox.showerror("Błąd Weryfikacji", f"Wystąpił błąd: {e}", parent=self)


    def delete_selected_dialogs(self):
        """Usuwa audio dla wszystkich zaznaczonych wierszy."""
        if not self.selected_line_indices or not self.app.audio_dir:
            return

        if self.current_audio_process and self.current_audio_process.poll() is None:
            messagebox.showwarning("Plik w użyciu", "Audio jest odtwarzane. Zatrzymaj je przed usunięciem.",
                                   parent=self)
            return

        # Zbierz wszystkie pliki do usunięcia
        files_to_delete = []
        for idx in self.selected_line_indices:
            line_obj = self.app.lines[idx]
            if getattr(line_obj, 'status_flag', None) == "DONE":
                continue

            line_num = idx + 1
            identifier = getattr(line_obj, 'uid', str(line_num))
            found_files = get_audio_candidates(identifier)
            if found_files:
                files_to_delete.extend(found_files)

        if not files_to_delete:
            return

        self.stop_audio()
        deleted = 0
        for file_path, _ in files_to_delete:
            try:
                os.remove(file_path)
                deleted += 1
            except Exception:
                pass
        self.update_audio_buttons_state()
        if deleted and hasattr(self.app, 'set_status'):
            self.app.set_status(f"Usunięto {deleted} plików audio.")

    def delete_selected_rows(self):
        """Usuwa zaznaczone wiersze oraz powiązane pliki audio (wszystkie dla danego UID)."""
        if not self.selected_line_indices:
            return

        # Filtruj linie oznaczone jako 'DONE'
        indices_to_delete = []
        for idx in self.selected_line_indices:
            line_obj = self.app.lines[idx]
            if getattr(line_obj, 'status_flag', None) != "DONE":
                indices_to_delete.append(idx)
        
        if not indices_to_delete:
            return

        count = len(indices_to_delete)
        if not messagebox.askyesno("Usuń wiersze", f"Czy na pewno chcesz usunąć {count} wierszy oraz wszystkie ich pliki audio?"):
            return

        indices = sorted(indices_to_delete, reverse=True)
        
        # Zatrzymaj odtwarzanie jeśli dotyczy usuwanego wiersza
        # Uproszczenie: zatrzymaj zawsze
        self.stop_audio()

        deleted_audio_count = 0
        uids_to_remove_from_db = []
        
        for idx in indices:
            if idx < 0 or idx >= len(self.app.lines):
                continue
            
            line_obj = self.app.lines[idx]
            identifier = getattr(line_obj, 'uid', None)
            
            if identifier:
                uids_to_remove_from_db.append(identifier)
                found_files = get_audio_candidates(identifier)
                for file_path, _ in found_files:
                    try:
                        if file_path.exists():
                            file_path.unlink()
                            deleted_audio_count += 1
                    except Exception as e:
                        from app.logger import Logger
                        Logger.error(f"Błąd usuwania pliku {file_path}: {e}")
            
            # Usuń wiersz z listy
            del self.app.lines[idx]

        # Trwałe usunięcie z CSV poprzez nadpisanie pliku
        if self.app.loaded_path:
             try:
                 from app.io import save_lines_to_file
                 save_lines_to_file(str(self.app.loaded_path), self.app.lines)
             except Exception as e:
                 from app.logger import Logger
                 Logger.error(f"Błąd podczas zapisywania zmian po usunięciu: {e}")

        # Wyczyść zaznaczenie
        self.selected_line_indices = []
        self.app.selected_line_index = None
        self.tree.selection_remove(self.tree.selection())

        # Odśwież UI
        self.set_preview(self.app.lines)
        # self.app.mark_as_unsaved() # Niepotrzebne, bo zapisaliśmy do CSV
        self.app.set_status(f"Usunięto {count} wierszy i {deleted_audio_count} plików audio.")
