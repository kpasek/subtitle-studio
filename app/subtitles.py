import shutil
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import subprocess
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from app.entity import Line
from tkinter import messagebox
import threading
import time
import json
import shutil

from app.io import update_line_in_csv
from app.patterns import (apply_patterns, apply_processing, 
                          add_replace_pattern_from_selection, add_remove_pattern_from_selection)
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
        self.selected_line_indices = []  # Lista zaznaczonych indeksów wierszy
        self.item_line_map: Dict[str, Line] = {}

        # Konfiguracja kolumn - tutaj można łatwo dodawać nowe kolumny w przyszłości
        self.columns_config = [
            {"id": "content", "text": "Tekst", "width": 600, "anchor": "w", "stretch": True},
            {"id": "duration", "text": "Czas", "width": 80, "anchor": "center", "stretch": False},
            {"id": "cps", "text": "CPS", "width": 70, "anchor": "center", "stretch": False},
            {"id": "similarity", "text": "SIM %", "width": 80, "anchor": "center", "stretch": False},
            {"id": "audio_file", "text": "Plik", "width": 250, "anchor": "w", "stretch": False},
        ]

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # --- Weryfikacja audio ---
        self.ver_running = False
        self.ver_stop_event = threading.Event()
        self.ver_analysis_results = []  # list of dicts per line
        self.ver_processed_indices = set()
        self.ver_cache = {}
        self.ver_cache_file = None
        if hasattr(self.app, 'loaded_path') and self.app.loaded_path:
            self.ver_cache_file = self.app.loaded_path.with_suffix('.cps_cache.json')
        self.ver_ffprobe_path = shutil.which('ffprobe')

        self._create_widgets()

    def _create_widgets(self):

        # --- Górny pasek stats_frame - Row 0 ---
        stats_frame = ctk.CTkFrame(self)
        stats_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkButton(stats_frame, text="Zatwierdź zmiany",
                      command=lambda: apply_processing(self.app),
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
                                               command=lambda: download_update(self.app),
                                               fg_color="#006400", hover_color="#004d00")
        self.app.update_button.pack(side="left", padx=5)
        self.app.update_button.pack_forget()

        self.app.lbl_filename = ctk.CTkLabel(stats_frame, text="Brak wczytanego pliku")
        self.app.lbl_filename.pack(side="left", anchor="w", padx=5)

        # --- Audio/Action buttons + Pasek Wyszukiwania - Row 1 ---
        audio_btn_frame = ctk.CTkFrame(self)
        audio_btn_frame.grid(row=1, column=0, sticky="ew", pady=(0, 5), padx=5)

        audio_btn_frame.grid_columnconfigure(4, weight=1)

        self.generate_button = ctk.CTkButton(audio_btn_frame, text="⚙️ Generuj", width=80,
                                             command=self.generate_selected_dialogs, state="disabled",
                                             fg_color="#2E8B57", hover_color="#1E613B")
        self.generate_button.grid(row=0, column=0, padx=4)

        self.verify_button = ctk.CTkButton(audio_btn_frame, text="✓ Weryfikuj", width=100,
                                           command=self.verify_selected_dialogs, state="disabled",
                                           fg_color="#1E90FF", hover_color="#4169E1")
        self.verify_button.grid(row=0, column=1, padx=4)

        self.delete_all_button = ctk.CTkButton(audio_btn_frame, text="🗑️ Usuń audio", width=100,
                                               command=self.delete_selected_dialogs, state="disabled",
                                               fg_color="#C51616", hover_color="#920F0F")
        self.delete_all_button.grid(row=0, column=2, padx=4)

        # --- Pasek Wyszukiwania ---
        ctk.CTkLabel(audio_btn_frame, text="Szukaj").grid(row=0, column=3, padx=(15, 5))

        # Pole do wyszukiwania tekstu
        self.search_entry = ctk.CTkEntry(audio_btn_frame, placeholder_text="Tekst")
        self.search_entry.grid(row=0, column=4, sticky="ew")
        self.search_entry.bind("<Return>", lambda event: apply_patterns(self.app))
        self.search_entry.bind("<Control-BackSpace>", lambda event: self.search_entry.delete(0, tk.END))

        self.search_button = ctk.CTkButton(audio_btn_frame, text="Szukaj", command=lambda: apply_patterns(self.app), width=60)
        self.search_button.grid(row=0, column=5, padx=(6, 0))
        self.filter_button = ctk.CTkButton(audio_btn_frame, text="Filtruj", command=self.open_filter_window, width=80)
        self.filter_button.grid(row=0, column=6, padx=(6, 0))

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

        # Zmienne do edycji inline
        self.inline_edit_entry = None
        self.inline_edit_item = None

    def _on_view_mode_change(self, value):
        apply_patterns(self.app)
        self.set_preview(self.app.lines)
        from app.project import save_app_setting
        save_app_setting(self.app, 'last_view_mode', value)



    def _sort_by_column(self, col_id: str):
        """Sortuje `self.app.lines` i `ver_analysis_results` według kolumny, toggle asc/desc."""
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
                if col_id == 'duration':
                    val = getattr(ln, 'audio_duration', 0.0)
                    return (0, float(val if val is not None else 0.0))
                if col_id == 'similarity':
                    val = getattr(ln, 'audio_similarity', 0.0)
                    if (val is None or val == 0.0) and i < len(self.ver_analysis_results):
                        val = self.ver_analysis_results[i].get('similarity', 0.0)
                    return (0, float(val if val is not None else 0.0))
                if col_id == 'cps':
                    # Uproszczone CPS do sortowania
                    txt = getattr(ln, 'tts_text', '') or getattr(ln, 'text', '') or ''
                    duration = float(getattr(ln, 'audio_duration', 0.0) or 0.0)
                    if duration > 0:
                        return (0, len(txt) / duration)
                    if i < len(self.ver_analysis_results):
                        return (0, float(self.ver_analysis_results[i].get('cps') or 0.0))
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
            print(f"[ERROR] Sort failed for col {col_id}: {e}")
            return
            
        self.app.lines = [ln for _, ln in indexed]
        
        if self.ver_analysis_results:
            new_results = []
            for old_idx, _ in indexed:
                if old_idx < len(self.ver_analysis_results):
                    new_results.append(self.ver_analysis_results[old_idx])
            self.ver_analysis_results = new_results

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
        # Wyczyść tabelę
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.item_line_map.clear()

        search_term = self.search_entry.get().lower()

        # Przygotuj dane do wstawienia
        # Jeśli w przyszłości lines_to_show będzie listą słowników/obiektów,
        # tutaj trzeba będzie dostosować mapowanie na kolumny.

        for i, item in enumerate(lines_to_show):
            if isinstance(item, str):
                line_text = item
                line_obj = None
            else:
                line_obj = item
                line_text = line_obj.get_text() if hasattr(line_obj, 'get_text') else (line_obj.text or '')

            line_tts_display = ''
            if line_obj is not None:
                if hasattr(line_obj, 'get_tts_text'):
                    line_tts_display = line_obj.get_tts_text() or ''
                else:
                    line_tts_display = getattr(line_obj, 'tts_text', '') or ''

            try:
                mode = self.app.view_mode.get()
                if line_obj is not None:
                    base_text = line_obj.get_text() if hasattr(line_obj, 'get_text') else (line_obj.text or '')
                    if mode == 'Napisy':
                        content_text = (base_text or '').lower()
                    elif mode == 'TTS':
                        content_text = (line_tts_display or '').lower()
                    else:
                        content_text = (base_text or '').lower()
                else:
                    content_text = (line_text or '').lower()
            except Exception:
                content_text = (line_text or '').lower()

            if search_term and search_term not in content_text:
                continue

            # Apply user filters if any
            f = getattr(self, 'filter_spec', {}) or {}
            # Try to get verification entry but prefer Line fields
            try:
                ar = self.ver_analysis_results[i] if i < len(getattr(self, 'ver_analysis_results', [])) else None
            except Exception:
                ar = None
            min_sim_filter = self._normalize_similarity_filter_value(f.get('min_sim'))
            max_sim_filter = self._normalize_similarity_filter_value(f.get('max_sim'))
            # text length
            try:
                if f.get('min_len') and len(content_text) < int(f.get('min_len')):
                    continue
                if f.get('max_len') and len(content_text) > int(f.get('max_len')):
                    continue
            except Exception:
                pass
            # cps
            try:
                # Jeśli filtr CPS jest ustawiony, pominąć linie bez weryfikacji
                # compute CPS from Line if available
                if line_obj is None:
                    cps_val = float(ar.get('cps') or 0) if ar else 0.0
                else:
                    try:
                        txt = (line_tts_display or '').strip('.?!')
                        from collections import Counter
                        stats = Counter(txt)
                        short = stats[','] + stats['-']
                        long = stats['.'] + stats['!'] + stats['?']
                        pauses = (short * 0.4) + (long * 0.6)
                        duration = float(getattr(line_obj, 'audio_duration', 0.0) or 0.0)
                        cps_val = len(txt) / (duration - pauses) if (duration - pauses) > 0 else 0.0
                    except Exception:
                        cps_val = float(ar.get('cps') or 0) if ar else 0.0
                if f.get('min_cps') is not None and f.get('min_cps') != '' and cps_val < float(f.get('min_cps')):
                    continue
                if f.get('max_cps') is not None and f.get('max_cps') != '' and cps_val > float(f.get('max_cps')):
                    continue
            except Exception:
                pass
            # similarity
            sim_val = 0.0
            try:
                # Jeśli filtr similarity jest ustawiony, pominąć linie bez weryfikacji
                if (f.get('min_sim') is not None and f.get('min_sim') != '') or (f.get('max_sim') is not None and f.get('max_sim') != ''):
                    # require a transcribed text or audio file to compute similarity
                    if line_obj is None and (not ar or ar.get('path') is None):
                        continue
                sim_val = float(getattr(line_obj, 'audio_similarity', 0.0) or 0.0) if line_obj else float(ar.get('similarity') or 0.0 if ar else 0.0)
                sim_val = max(0.0, min(sim_val, 1.0))
                if min_sim_filter is not None and sim_val < min_sim_filter:
                    continue
                if max_sim_filter is not None and sim_val > max_sim_filter:
                    continue
            except Exception:
                sim_val = 0.0
            # show option
            try:
                show = f.get('show')
                if show == 'Wygenerowane':
                    # Pokaż tylko linie które mają audio
                    has_audio = bool(getattr(line_obj, 'audio_filename', '') or (ar and ar.get('path')))
                    if not has_audio:
                        continue
                elif show == 'Niewygenerowane':
                    has_audio = bool(getattr(line_obj, 'audio_filename', '') or (ar and ar.get('path')))
                    if has_audio:
                        continue
            except Exception:
                pass

            # Budowanie wartości dla wiersza zgodnie z self.columns_config
            row_values = []
            for col in self.columns_config:
                col_id = col["id"]
                if col_id == "content":
                    if line_obj is not None:
                        if self.app.view_mode.get() == 'TTS':
                            row_values.append(line_tts_display)
                        else:
                            line_content = line_obj.get_text() if hasattr(line_obj, 'get_text') else (line_obj.text or '')
                            row_values.append(line_content)
                    else:
                        row_values.append(line_text)
                else:
                    row_values.append("")

            # Fill columns from Line object first, fallback to ver_analysis_results
            col_pos = {c['id']: idx for idx, c in enumerate(self.columns_config)}
            try:
                if 'duration' in col_pos:
                    duration_val = float(getattr(line_obj, 'audio_duration', 0.0) or 0.0) if line_obj else (self.ver_analysis_results[i].get('duration', 0) if i < len(self.ver_analysis_results) else 0)
                    row_values[col_pos['duration']] = f"{duration_val:.2f}" if duration_val > 0 else '-'
                if 'cps' in col_pos:
                    try:
                        cps_val = 0.0
                        if line_obj is not None:
                            txt = (line_tts_display or '').strip('.?!')
                            from collections import Counter
                            stats = Counter(txt)
                            short = stats[','] + stats['-']
                            long = stats['.'] + stats['!'] + stats['?']
                            pauses = (short * 0.4) + (long * 0.6)
                            duration = float(getattr(line_obj, 'audio_duration', 0.0) or 0.0)
                            cps_val = len(txt) / (duration - pauses) if (duration - pauses) > 0 else 0.0
                        else:
                            cps_val = float(self.ver_analysis_results[i].get('cps') or 0) if i < len(self.ver_analysis_results) else 0.0
                    except Exception:
                        cps_val = 0.0
                    row_values[col_pos['cps']] = f"{cps_val:.1f}" if (cps_val and cps_val > 0) else '-'
                if 'similarity' in col_pos:
                    sim_display = self._format_similarity_percent(sim_val)
                    row_values[col_pos['similarity']] = sim_display if sim_display else '-'
                if 'format' in col_pos:
                    fmt = (getattr(line_obj, 'audio_format', '') or '')
                    if not fmt and i < len(self.ver_analysis_results):
                        fmt = (self.ver_analysis_results[i].get('ext') or '')
                    row_values[col_pos['format']] = (fmt or '').upper()
                if 'audio_file' in col_pos:
                    path = None
                    if line_obj and getattr(line_obj, 'audio_filename', ''):
                        path = str(Path(getattr(self, 'app').audio_dir or Path('.')) / line_obj.audio_filename)
                    elif i < len(self.ver_analysis_results):
                        path = self.ver_analysis_results[i].get('path')
                    row_values[col_pos['audio_file']] = Path(path).name if path else ''
            except Exception:
                pass

            # Wstawienie wiersza
            item_id = self.tree.insert("", "end", values=tuple(row_values))
            if line_obj is not None:
                self.item_line_map[item_id] = line_obj

        # NOWE: Jeśli użytkownik miał zaznaczenie (selected_line_indices jest nie puste),
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
            else:
                self.app.selected_line_index = None
        else:
            self.app.selected_line_index = None
            self.update_audio_buttons_state()

    @staticmethod
    def _format_similarity_percent(value: float | None) -> str | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        numeric = max(0.0, min(numeric, 1.0))
        return f"{numeric * 100:.0f}%"

    @staticmethod
    def _normalize_similarity_filter_value(value: float | str | None) -> float | None:
        if value is None or value == '':
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric > 1:
            numeric = numeric / 100.0
        numeric = max(0.0, min(numeric, 1.0))
        return numeric

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
        new_text = self.inline_edit_entry.get()
        
        # Usuń entry widget
        self.inline_edit_entry.destroy()
        self.inline_edit_entry = None
        self.inline_edit_item = None
        
        # Zaktualizuj bezpośrednio w app.lines (nie w manual_edits/tts_edits)
        mode = self.app.view_mode.get()
        if mode == "Napisy":
            self.app.lines[line_idx].text = new_text
        elif mode == "TTS":
            self.app.lines[line_idx].tts_text = new_text
        
        # Zapisz do CSV bezpośrednio
        try:
            if self.app.loaded_path:
                update_line_in_csv(str(self.app.loaded_path), line_idx, self.app.lines[line_idx])
        except Exception as e:
            print(f"Błąd zapisu do CSV: {e}")
        
        # Odśwież UI
        apply_patterns(self.app)
        self.set_preview(self.app.lines)

    def _cancel_inline_edit(self, event=None):
        """Anuluje edycję inline bez zmian."""
        if self.inline_edit_entry:
            self.inline_edit_entry.destroy()
            self.inline_edit_entry = None
            self.inline_edit_item = None

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

        can_gen = self.generate_button.cget("state") == "normal"
        can_verify = self.verify_button.cget("state") == "normal"
        can_del = self.delete_all_button.cget("state") == "normal"
        can_edit = self.app.view_mode.get() != "Oryginał"  # Edycja możliwa tylko w trybach Napisy/TTS

        menu.add_command(label="⚙️ Generuj audio (Ctrl+G)", command=self.generate_selected_dialogs,
                         state=tk.NORMAL if can_gen else tk.DISABLED)
        menu.add_command(label="✓ Weryfikuj audio (Ctrl+V)", command=self.verify_selected_dialogs,
                         state=tk.NORMAL if can_verify else tk.DISABLED)
        menu.add_command(label="🗑️ Usuń audio (Ctrl+X)", command=self.delete_selected_dialogs,
                         state=tk.NORMAL if can_del else tk.DISABLED)
        menu.add_separator()
        menu.add_command(label="📄 Kopiuj linię (Ctrl+C)", command=lambda: self.app._on_ctrl_c_from_menu(),
                         state=tk.NORMAL)
        menu.add_command(label="❌ Wyczyść treść linii (Del)", command=lambda: self.app._clear_selected_line_content(),
                         state=tk.NORMAL if can_edit else tk.DISABLED)
        menu.add_separator()
        menu.add_command(label="➕ Dodaj wzorzec zamieniający (Ctrl+Klik)",
                         command=lambda: add_replace_pattern_from_selection(self.app, from_menu=True), state=tk.NORMAL)

        # Obliczamy ID. current_line_index jest liczony od 0, a pliki od 1.
        current_id = self.app.selected_line_index + 1

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # --- Weryfikacja audio (zintegrowana) ---
    def start_verification(self, force_refresh=False, stop_on_error=False, auto_sync=False, ignore_short=True):
        if not self.app.audio_dir:
            messagebox.showwarning("Brak audio", "Najpierw wybierz katalog audio.", parent=self)
            return
        if not self.app.lines:
            messagebox.showwarning("Brak tekstu", "Brak napisów do weryfikacji.", parent=self)
            return

        # Use VerificationManager (non-blocking) if available
        if self.ver_running:
            return

        self.ver_running = True
        self.ver_stop_event.clear()

        if force_refresh:
            self.ver_analysis_results = []
            self.ver_processed_indices.clear()
            self.ver_cache = {}

        # Ensure results list has entries for each line
        def _line_verification_text(line_obj):
            getter = getattr(line_obj, 'get_tts_text', None)
            candidate = getter() if callable(getter) else getattr(line_obj, 'tts_text', '')
            return (candidate or '').strip()

        if not self.ver_analysis_results:
            for i, line in enumerate(self.app.lines):
                self.ver_analysis_results.append({
                    'id': i + 1,
                    'text': _line_verification_text(line),
                    'duration': 0.0,
                    'cps': 0.0,
                    'raw_status': 'PENDING',
                    'path': None,
                    'ext': '',
                    'display_status': 'PENDING'
                })

        try:
            cpu_count = os.cpu_count() or 4
        except Exception:
            cpu_count = 4
        try:
            workers_cfg = int(self.app.global_config.get('verification_workers', self.app.global_config.get('conversion_workers', max(1, cpu_count // 2))))
        except Exception:
            workers_cfg = max(1, cpu_count // 2)
        workers = max(1, min(workers_cfg, cpu_count * 2))

        lines_texts = [_line_verification_text(line) for line in self.app.lines]
        line_uids = [getattr(l, 'uid', f"output1 ({i + 1})") for i, l in enumerate(self.app.lines)]
        audio_dir = str(self.app.audio_dir)
        ffprobe = shutil.which('ffprobe')

        if VerificationManager is None:
            messagebox.showerror("Błąd", "Brak VerificationManager.", parent=self)
            self.ver_running = False
            return

        manager = VerificationManager.get_instance()

        def apply_cb(results: dict):
            # this is called in manager thread; schedule work on main thread
            try:
                self.after(0, lambda r=results: self._apply_verification_results(r))
            except Exception:
                pass

        job = VerificationJob(
            project_path=str(getattr(self.app, 'current_project_path', '')),
            audio_dir=audio_dir,
            lines_texts=lines_texts,
            line_uids=line_uids,
            force_refresh=force_refresh,
            ignore_short=ignore_short,
            ffprobe=ffprobe,
            workers=workers,
            apply_callback=apply_cb
        )

        manager.add_job(job)
        try:
            self.after(0, lambda: self.app.set_status("Weryfikacja uruchomiona"))
        except Exception:
            pass
        return
    def _get_audio_duration(self, file_path, ext):
        file_path = str(file_path)
        # Try ffprobe
        if self.ver_ffprobe_path:
            try:
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                cmd = [self.ver_ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                       "-of", "default=noprint_wrappers=1:nokey=1", file_path]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo)
                if res.returncode == 0 and res.stdout.strip():
                    return float(res.stdout.strip()), None
                return -1.0, res.stderr
            except Exception as e:
                return -1.0, str(e)
        return -1.0, 'Brak ffprobe'

    def _refresh_verification_view(self):
        # Odśwież TYLKO zweryfikowane wiersze zamiast całej tabeli
        # Mapowanie UID -> item_id w tabeli dla szybkiego dostępu
        uid_to_item = {getattr(ln, 'uid', id(ln)): iid for iid, ln in self.item_line_map.items()}
        
        # Aktualizuj wartości dla każdego zaznaczonego wiersza (lub tych które mogły ulec zmianie)
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
                    # Update duration
                    if 'duration' in col_pos:
                        duration_val = float(getattr(line_obj, 'audio_duration', 0.0) or 0.0)
                        row_values[col_pos['duration']] = f"{duration_val:.2f}" if duration_val > 0 else '-'
                    
                    # Update CPS
                    if 'cps' in col_pos:
                        try:
                            if hasattr(line_obj, 'get_tts_text'):
                                txt_source = line_obj.get_tts_text()
                            else:
                                txt_source = getattr(line_obj, 'tts_text', '')
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
                    
                    # Update similarity
                    if 'similarity' in col_pos:
                        similarity_val = float(getattr(line_obj, 'audio_similarity', 0.0) or 0.0)
                        sim_display = self._format_similarity_percent(similarity_val)
                        row_values[col_pos['similarity']] = sim_display if sim_display else '-'
                    
                    # Update format
                    if 'format' in col_pos:
                        fmt = (getattr(line_obj, 'audio_format', '') or '')
                        row_values[col_pos['format']] = (fmt or '').upper()
                    
                    # Update audio file
                    if 'audio_file' in col_pos:
                        path = None
                        if getattr(line_obj, 'audio_filename', ''):
                            path = str(Path(getattr(self, 'app').audio_dir or Path('.')) / line_obj.audio_filename)
                        row_values[col_pos['audio_file']] = Path(path).name if path else ''
                    
                    # Zaktualizuj wiersz w tabeli
                    self.tree.item(item_id, values=tuple(row_values))
                    updated_count += 1
                    
                except Exception:
                    pass
        
        # Przywróć zaznaczenie
        try:
            items_to_select = [line_to_item[self.app.lines[idx]] for idx in self.selected_line_indices 
                               if 0 <= idx < len(self.app.lines) and self.app.lines[idx] in line_to_item]
            
            if items_to_select:
                self.tree.selection_set(*items_to_select)
                self.tree.see(items_to_select[0])
        except Exception:
            pass

    def _apply_verification_results(self, data: dict):
        """
        Apply merged verification results (called on main thread).
        `data` is a dict mapping string id -> entry dict produced by worker.
        """
        updates_since_save = 0
        any_changes = False
        
        # Upewnij się że ver_analysis_results ma wystarczającą długość
        while len(self.ver_analysis_results) < len(self.app.lines):
            idx = len(self.ver_analysis_results)
            self.ver_analysis_results.append({
                'id': idx + 1,
                'text': self.app.lines[idx].tts_text if idx < len(self.app.lines) else '',
                'duration': 0.0,
                'cps': 0.0,
                'raw_status': 'PENDING',
                'path': None,
                'ext': '',
                'display_status': 'PENDING'
            })
        
        for k, v in data.items():
            if k == '__done':
                continue
            try:
                idx = int(k) - 1
                if idx < 0 or idx >= len(self.app.lines):
                    continue
                line = self.app.lines[idx]
                # update Line fields
                try:
                    line.audio_duration = float(v.get('duration') or 0)
                except Exception:
                    line.audio_duration = 0.0
                path = v.get('path')
                if path:
                    try:
                        line.audio_filename = Path(path).name
                    except Exception:
                        line.audio_filename = str(path)
                line.audio_format = (v.get('ext') or '').upper()
                # similarity and transcribed text
                try:
                    line.audio_similarity = float(v.get('similarity') or 0.0)
                except Exception:
                    line.audio_similarity = 0.0
                line.audio_transcribed_text = v.get('transcribed_text', '') or v.get('transcribed_text', '')
                duration_value = float(v.get('duration') or 0)
                cps_value = float(v.get('cps') or 0)
                similarity_value = line.audio_similarity
                print(f"[VERIFY_SUMMARY] line {idx + 1}: duration={duration_value:.2f}s cps={cps_value:.1f} similarity={similarity_value:.3f}")

                # update ver_analysis_results
                if idx < len(self.ver_analysis_results):
                    try:
                        self.ver_analysis_results[idx].update({
                            'duration': float(v.get('duration') or 0),
                            'cps': float(v.get('cps') or 0),
                            'raw_status': v.get('raw_status'),
                            'path': Path(v['path']) if v.get('path') else None,
                            'ext': v.get('ext') or '',
                            'display_status': v.get('display_status'),
                            'similarity': float(v.get('similarity') or 0.0),
                            'transcribed_text': v.get('transcribed_text', '')
                        })
                    except Exception:
                        pass

                # persist to cache dict
                try:
                    self.ver_cache[str(idx + 1)] = {
                        'text': v.get('text', ''),
                        'duration': float(v.get('duration') or 0),
                        'path': v.get('path'),
                        'ext': v.get('ext') or '',
                        'similarity': float(v.get('similarity') or 0.0),
                        'transcribed_text': v.get('transcribed_text', ''),
                        'error': None
                    }
                except Exception:
                    pass

                updates_since_save += 1
                any_changes = True
                # mark processed
                try:
                    self.ver_processed_indices.add(idx)
                except Exception:
                    pass
            except Exception:
                continue

        # handle special flags
        if '__done' in data or data.get('__done') is True:
            # finalization
            self.ver_running = False
            try:
                self.after(0, lambda: self.app.set_status('Weryfikacja zakończona'))
            except Exception:
                pass

        if any_changes:
            # save cache file
            try:
                if self.ver_cache_file:
                    with open(self.ver_cache_file, 'w', encoding='utf-8') as f:
                        json.dump(self.ver_cache, f, ensure_ascii=False)
            except Exception:
                pass

            # ZAMIAST set_preview() który resetuje całą tabelę - używamy targeted refresh!
            # Spróbuj najpierw targeted refresh (dla już widocznych wierszy)
            try:
                self._refresh_verification_view()
            except Exception as e:
                print(f"[APPLY_RESULTS] BŁĄD w _refresh_verification_view: {e}")

            # autosave lines to CSV; perform best-effort
            try:
                if getattr(self.app, 'loaded_path', None):
                    from app.io import save_lines_to_file
                    save_lines_to_file(str(self.app.loaded_path), self.app.lines)
            except Exception as e:
                print(f"[APPLY_RESULTS] BŁĄD CSV: {e}")

    def stop_verification(self):
        """Stop currently running verification via manager"""
        try:
            from audio.verification_manager import VerificationManager
            VerificationManager.get_instance().cancel_current()
        except Exception:
            pass
        self.ver_running = False
        self.ver_stop_event.set()

    def _verification_watcher(self):
        """Thread in main process: monitors all worker out-files and applies results to Line objects.
        Also performs autosave every 100 updates or every 10 seconds.
        """
        out_files = getattr(self, '_ver_out_files', None)
        if not out_files:
            return
        last_mtimes = {str(p): 0 for p in out_files}
        updates_since_save = 0
        last_save_time = time.time()

        while self.ver_running and not self.ver_stop_event.is_set():
            try:
                any_changes = False
                for outp in list(out_files):
                    p = Path(outp)
                    if not p.exists():
                        continue
                    m = p.stat().st_mtime
                    key = str(p)
                    if m == last_mtimes.get(key):
                        continue
                    last_mtimes[key] = m
                    try:
                        with open(p, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                    except Exception:
                        continue

                    applied = 0
                    for k, v in data.items():
                        try:
                            idx = int(k) - 1
                            if idx < 0 or idx >= len(self.app.lines):
                                continue
                            line = self.app.lines[idx]
                            line.audio_duration = float(v.get('duration') or 0)
                            path = v.get('path')
                            if path:
                                line.audio_filename = Path(path).name
                            line.audio_status = v.get('display_status') or v.get('raw_status') or ''
                            line.audio_format = (v.get('ext') or '').upper()
                            try:
                                line.audio_similarity = float(v.get('similarity') or 0.0)
                            except Exception:
                                line.audio_similarity = 0.0
                            line.audio_transcribed_text = v.get('transcribed_text', '')

                            if idx < len(self.ver_analysis_results):
                                try:
                                    self.ver_analysis_results[idx].update({
                                        'duration': float(v.get('duration') or 0),
                                        'cps': float(v.get('cps') or 0),
                                        'raw_status': v.get('raw_status'),
                                        'path': Path(v['path']) if v.get('path') else None,
                                        'ext': v.get('ext') or '',
                                        'display_status': v.get('display_status'),
                                        'similarity': float(v.get('similarity') or 0.0),
                                        'transcribed_text': v.get('transcribed_text', '')
                                    })
                                except Exception:
                                    pass

                            # persist to cache dict
                            try:
                                self.ver_cache[str(idx+1)] = {
                                    'text': v.get('text', ''),
                                    'duration': float(v.get('duration') or 0),
                                    'path': v.get('path'),
                                    'ext': v.get('ext') or '',
                                    'similarity': float(v.get('similarity') or 0.0),
                                    'transcribed_text': v.get('transcribed_text', ''),
                                    'error': None
                                }
                            except Exception:
                                pass

                            applied += 1
                        except Exception:
                            continue

                    if applied:
                        updates_since_save += applied
                        any_changes = True

                if any_changes:
                    # save cache
                    try:
                        if self.ver_cache_file:
                            with open(self.ver_cache_file, 'w', encoding='utf-8') as f:
                                json.dump(self.ver_cache, f, ensure_ascii=False)
                    except Exception:
                        pass
                    # refresh UI
                    try:
                        self.after(0, self._refresh_verification_view)
                    except Exception:
                        pass

                # autosave lines to CSV every 100 updates or every 10 seconds
                try:
                    if (updates_since_save >= 100) or (time.time() - last_save_time >= 10):
                        if getattr(self.app, 'loaded_path', None):
                            try:
                                from app.io import save_lines_to_file
                                save_lines_to_file(str(self.app.loaded_path), self.app.lines)
                                last_save_time = time.time()
                                updates_since_save = 0
                            except Exception:
                                pass
                except Exception:
                    pass

                time.sleep(0.5)
            except Exception:
                time.sleep(0.5)

        # finalize status and cleanup out files
        try:
            self.after(0, lambda: self.app.set_status('Weryfikacja zakończona'))
        except Exception:
            pass
        for outp in getattr(self, '_ver_out_files', []):
            try:
                p = Path(outp)
                if p.exists():
                    p.unlink()
            except Exception:
                pass
    
    
    def delete_all_bad_audio_verification(self):
        # Collect bad items (based on display_status)
        to_del = []
        for item in self.ver_analysis_results:
            if not item.get('path'):
                continue
            status = item.get('display_status', 'OK')
            if status not in ['OK', 'SHORT', 'MISSING', 'PENDING']:
                to_del.append(item)

        if not to_del:
            messagebox.showinfo("Info", "Brak błędnych plików do usunięcia (w aktualnym widoku).", parent=self)
            return

        if not messagebox.askyesno("Potwierdź", f"Usunąć {len(to_del)} błędnych plików?", parent=self):
            return

        count = 0
        errors = []
        for item in to_del:
            try:
                path_to_remove = Path(item['path'])
                if path_to_remove.exists():
                    os.remove(path_to_remove)
                idx = item['id'] - 1
                self.ver_analysis_results[idx]['raw_status'] = 'MISSING'
                self.ver_analysis_results[idx]['path'] = None
                self.ver_analysis_results[idx]['duration'] = 0
                self.ver_analysis_results[idx]['display_status'] = 'MISSING'
                if str(item['id']) in self.ver_cache:
                    del self.ver_cache[str(item['id'])]
                count += 1
            except Exception as e:
                errors.append(f"ID {item['id']}: {str(e)}")

        self._refresh_verification_view()
        if errors:
            messagebox.showwarning("Wynik", f"Usunięto {count} plików. Błędy:\n" + "\n".join(errors[:10]), parent=self)
        else:
            messagebox.showinfo("Zakończono", f"Pomyślnie usunięto {count} plików.", parent=self)

    def open_verification_folder(self):
        # Open folder for selected item or audio_dir
        sel = self.tree.selection()
        item = None
        if sel:
            vals = self.tree.item(sel[0], 'values')
            try:
                idx = int(vals[0]) - 1
                item = self.ver_analysis_results[idx] if idx < len(self.ver_analysis_results) else None
            except Exception:
                item = None

        p = item.get('path') if item and item.get('path') else self.app.audio_dir
        path = Path(p).parent if p else self.app.audio_dir
        if os.name == 'nt':
            os.startfile(path)
        else:
            subprocess.call(['xdg-open', path])

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
        except Exception:
            pass

    def _normalize_uid(self, uid: str) -> str:
        """Konwertuje sam UUID na pełną nazwę pliku output1 (uid)"""
        if uid.startswith("output1 ("):
            return uid
        return f"output1 ({uid})"

    def _find_audio_files(self, identifier: str) -> List[Tuple[Path, bool]]:
        if not self.app.audio_dir:
            return []
        base = self._normalize_uid(identifier)
        candidates = [
            (self.app.audio_dir / f"{base}.wav", False),
            (self.app.audio_dir / f"{base}.mp3", False),
            (self.app.audio_dir / f"{base}.ogg", False),
        ]
        return [(f, ready) for f, ready in candidates if f.exists()]

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
                
                # Próba 1: Użycie zapisanej nazwy pliku w obiekcie Line
                found_files = []
                if hasattr(selected_line, 'audio_filename') and selected_line.audio_filename:
                    audio_path = self.app.audio_dir / selected_line.audio_filename
                    if audio_path.exists():
                        found_files.append((audio_path, True))
                
                # Próba 2: Szukanie po UID (standardowa konwencja)
                if not found_files:
                    uid = getattr(selected_line, 'uid', None)
                    if uid:
                        found_files = self._find_audio_files(uid)
                
                # Próba 3: Szukanie po starym formacie indeksu (rezerwowo)
                if not found_files:
                    found_files = self._find_audio_files(f"output1 ({self.app.selected_line_index + 1})")

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

        # Logika wyszukiwania pliku
        file_to_play = None
        
        # Próba 1: Jeśli obiekt Line ma zapisaną nazwę pliku
        if hasattr(line_obj, 'audio_filename') and line_obj.audio_filename:
            path = self.app.audio_dir / line_obj.audio_filename
            if path.exists():
                file_to_play = path

        # Próba 2: Szukanie po UID lub identyfikatorze
        if not file_to_play:
            identifier = getattr(line_obj, 'uid', None)
            if identifier:
                files = self._find_audio_files(identifier)
                if files:
                    file_to_play = files[0][0]

        # Próba 3: Fallback na indeks (stara konwencja)
        if not file_to_play:
            try:
                idx = self.app.lines.index(line_obj)
                identifier = f"output1 ({idx + 1})"
                files = self._find_audio_files(identifier)
                if files:
                    file_to_play = files[0][0]
            except Exception:
                pass

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

    def generate_selected_dialogs(self):
        """Generuje audio dla wszystkich zaznaczonych wierszy."""
        if not self.selected_line_indices or not self.app.audio_dir:
            return

        lines_to_gen = []
        for idx in self.selected_line_indices:
            try:
                line_no = idx + 1
                line_obj = self.app.lines[idx]
                getter = getattr(line_obj, 'get_tts_text', None)
                candidate = getter() if callable(getter) else getattr(line_obj, 'tts_text', '')
                text = (candidate or '').strip()
                if not text:
                    continue
                uid = getattr(line_obj, 'uid', f"output1 ({line_no})")
                lines_to_gen.append((uid, text))
            except (IndexError, ValueError):
                continue

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
        if not self.selected_line_indices or not self.app.audio_dir:
            return

        if self.ver_running:
            messagebox.showinfo("Weryfikacja", "Weryfikacja jest już w toku.", parent=self)
            return

        if VerificationManager is None:
            messagebox.showerror("Błąd", "Brak VerificationManager.", parent=self)
            return

        self.ver_running = True
        
        # Inicjalizuj ver_analysis_results z całą listą linii
        def _resolve_verification_text(line_obj):
            getter = getattr(line_obj, 'get_tts_text', None)
            candidate = getter() if callable(getter) else getattr(line_obj, 'tts_text', '')
            return (candidate or '').strip()

        if not self.ver_analysis_results or len(self.ver_analysis_results) < len(self.app.lines):
            self.ver_analysis_results = []
            for i, line in enumerate(self.app.lines):
                self.ver_analysis_results.append({
                    'id': i + 1,
                    'text': _resolve_verification_text(line),
                    'duration': 0.0,
                    'cps': 0.0,
                    'raw_status': 'PENDING',
                    'path': None,
                    'ext': '',
                    'display_status': 'PENDING'
                })
        
        self.app.set_status(f"Weryfikacja {len(self.selected_line_indices)} linii...")

        # Uruchom weryfikację w osobnym wątku aby nie blokować UI
        thread = threading.Thread(
            target=self._verify_selected_lines_thread,
            args=(list(self.selected_line_indices),),
            daemon=True
        )
        thread.start()

    def _verify_selected_lines_thread(self, selected_indices: List[int]):
        """Worker thread dla weryfikacji zaznaczonych linii."""
        try:
            ffprobe = shutil.which('ffprobe')
            audio_dir = str(self.app.audio_dir)
            results = {}
            def _thread_line_text(line_obj, idx):
                getter = getattr(line_obj, 'get_tts_text', None)
                candidate = getter() if callable(getter) else getattr(line_obj, 'tts_text', '')
                return (candidate or '').strip()

            for line_idx in selected_indices:
                if line_idx < 0 or line_idx >= len(self.app.lines):
                    continue

                try:
                    line = self.app.lines[line_idx]
                    line_id = line_idx + 1  # 1-based ID
                    line_uid = getattr(line, 'uid', str(line_id))
                    if not self._find_audio_files(line_uid):
                        results[str(line_id)] = {
                            'id': line_id,
                            'text': _thread_line_text(line, line_idx),
                            'duration': 0.0,
                            'cps': 0.0,
                            'raw_status': 'MISSING',
                            'path': None,
                            'ext': '',
                            'display_status': 'MISSING'
                        }
                        continue

                    # Weryfikuj pojedynczą linię
                    result = VerificationManager.verify_line(
                        line=line,
                        audio_dir=audio_dir,
                        line_id=line_id,
                        line_uid=line_uid,
                        ffprobe_path=ffprobe,
                        ignore_short=True,
                        verify_duration=True
                    )
                    results[str(line_id)] = result
                except Exception as e:
                    results[str(line_idx + 1)] = {
                        'id': line_idx + 1,
                        'text': _thread_line_text(self.app.lines[line_idx], line_idx) if line_idx < len(self.app.lines) else '',
                        'duration': 0.0,
                        'cps': 0.0,
                        'raw_status': 'ERROR',
                        'path': None,
                        'ext': '',
                        'display_status': f'ERROR: {str(e)[:30]}'
                    }

            # Dodaj marker końca
            results['__done'] = True

            # Zaplanuj aktualizację UI na głównym wątku
            self.after(0, lambda r=results: self._apply_verification_results(r))

        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Błąd weryfikacji", f"Błąd: {str(e)}", parent=self))
        finally:
            self.after(0, lambda: setattr(self, 'ver_running', False))

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
            line_num = idx + 1
            line_obj = self.app.lines[idx]
            identifier = getattr(line_obj, 'uid', f"output1 ({line_num})")
            found_files = self._find_audio_files(identifier)
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


# --- Process entry function (runs in separate process) ---
def _verification_process_entry(audio_dir: str, lines_texts: list, out_file: str, ffprobe_path: str, force_refresh: bool, ignore_short: bool, worker_idx: int = 0, total_workers: int = 1, line_uids: Optional[list] = None):
    import json
    import subprocess
    from pathlib import Path
    from collections import Counter

    audio_dir_p = Path(audio_dir) if audio_dir else Path('.')
    results = {}

    def write_atomic(dct):
        tmp = Path(out_file + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as tf:
            json.dump(dct, tf, ensure_ascii=False)
        tmp.replace(out_file)

    def _normalize_uid(uid: str) -> str:
        """Konwertuje sam UUID na pełną nazwę pliku output1 (uid)"""
        if uid.startswith("output1 ("):
            return uid
        return f"output1 ({uid})"

    for i, text in enumerate(lines_texts):
        # distribute work among workers: only process indices matching this worker
        if total_workers and (i % total_workers) != worker_idx:
            continue
        ident = str(i + 1)
        uid = None
        if line_uids and i < len(line_uids):
            uid = line_uids[i]
        tts = (text or '').strip()
        entry = {'id': i+1, 'text': tts, 'duration': 0.0, 'cps': 0.0, 'raw_status': 'PENDING', 'path': None, 'ext': '', 'display_status': 'PENDING'}
        if not tts:
            results[ident] = entry
            write_atomic(results)
            continue

        # find file
        audio_file = None
        found_ext = ''
        if uid:
            base = _normalize_uid(uid)
        else:
            base = f"output1 ({ident})"
        candidates = [
            (audio_dir_p / f"{base}.wav", 'wav'),
            (audio_dir_p / f"{base}.mp3", 'mp3'),
            (audio_dir_p / 'ready' / f"{base}.ogg", 'ogg'),
            (audio_dir_p / 'ready' / f"{base}.mp3", 'mp3')
        ]
        for p, ext in candidates:
            if p.exists():
                audio_file = p
                found_ext = ext
                break


        duration = 0.0
        if audio_file and ffprobe_path:
            try:
                res = subprocess.run([ffprobe_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_file)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    duration = float(res.stdout.strip())
                else:
                    duration = -1.0
            except Exception:
                duration = -1.0

        raw_status = 'OK'
        cps = 0.0
        if not audio_file:
            raw_status = 'MISSING'
        elif duration < 0:
            raw_status = 'ERROR'
        elif duration == 0:
            raw_status = 'EMPTY'
        else:
            stats = Counter(tts.strip('.?!'))
            short = stats[','] + stats['-']
            long = stats['.'] + stats['!'] + stats['?']
            pauses = (short * 0.4) + (long * 0.6)
            try:
                cps = len(tts) / (duration - pauses)
            except Exception:
                cps = 0.0

        entry.update({'duration': duration, 'cps': cps, 'raw_status': raw_status, 'path': str(audio_file) if audio_file else None, 'ext': found_ext})

        # display status
        if raw_status != 'OK':
            entry['display_status'] = raw_status
        else:
            if ignore_short and len(tts) < 5:
                entry['display_status'] = 'SHORT'
            else:
                min_cps = 7.0
                max_cps = 20.0
                if cps < min_cps:
                    entry['display_status'] = f"ZA WOLNO (<{min_cps:.1f})"
                elif cps > max_cps:
                    entry['display_status'] = f"ZA SZYBKO (>{max_cps:.1f})"
                else:
                    entry['display_status'] = 'OK'

        results[ident] = entry
        write_atomic(results)
    # final write
    write_atomic(results)