import shutil
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import subprocess
import os
from pathlib import Path
from typing import List, Tuple, Optional
from app.entity import Line
from tkinter import messagebox
import threading
import time
import json
import shutil

from app.io import update_line_in_csv

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

        # Konfiguracja kolumn - tutaj można łatwo dodawać nowe kolumny w przyszłości
        self.columns_config = [
            {"id": "line_nr", "text": "Nr", "width": 40, "anchor": "center"},
            {"id": "content", "text": "Tekst", "width": 500, "anchor": "w"},
            {"id": "duration", "text": "Czas [s]", "width": 80, "anchor": "center"},
            {"id": "cps", "text": "CPS", "width": 60, "anchor": "center"},
            {"id": "similarity", "text": "Podobieństwo", "width": 120, "anchor": "center"},
            {"id": "format", "text": "Format", "width": 60, "anchor": "center"},
            {"id": "audio_file", "text": "Plik audio", "width": 200, "anchor": "w"},
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
        self.filter_button = ctk.CTkButton(audio_btn_frame, text="Filtruj", command=self.open_filter_window, width=80)
        self.filter_button.grid(row=0, column=7, padx=(6, 0))

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
        # Obsługa Ctrl+Klik (edycja inline)
        self.tree.bind("<Control-Button-1>", self._start_inline_edit)

        # Zmienne do edycji inline
        self.inline_edit_entry = None
        self.inline_edit_item = None

    def _on_view_mode_change(self, value):
        self.app.apply_patterns()
        self.set_preview(self.app.lines)
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



    def _sort_by_column(self, col_id: str):
        """Sortuje `self.app.lines` i `ver_analysis_results` według kolumny, toggle asc/desc."""
        # Initialize sort state dict
        if not hasattr(self, '_sort_state'):
            self._sort_state = {}
        asc = not self._sort_state.get(col_id, True)
        self._sort_state[col_id] = asc

        def key_fn(idx_line):
            i, ln = idx_line
            try:
                if col_id == 'line_nr':
                    return (0, i)  # (nie-None, wartość)
                if col_id == 'content':
                    return (0, (ln.text or '').lower())
                if col_id == 'duration':
                    return (0, float(getattr(ln, 'audio_duration', 0.0) or 0.0))
                if col_id == 'similarity':
                    # Kolumna similarity z Line.audio_similarity lub ver_analysis_results
                    try:
                        sim = float(getattr(ln, 'audio_similarity', 0.0) or 0.0)
                        if sim is not None:
                            return (0, sim)
                    except (TypeError, ValueError):
                        pass
                    if i < len(self.ver_analysis_results):
                        try:
                            sim = self.ver_analysis_results[i].get('similarity')
                            if sim is not None:
                                return (0, float(sim))
                        except (TypeError, ValueError):
                            pass
                    return (1, 0.0)  # None wartości na koniec
                if col_id == 'cps':
                    # Prefer Line-based CPS calculation, fallback to ver_analysis_results
                    try:
                        txt = (ln.tts_text or '').strip('.?!')
                        from collections import Counter
                        stats = Counter(txt)
                        short = stats[','] + stats['-']
                        long = stats['.'] + stats['!'] + stats['?']
                        pauses = (short * 0.4) + (long * 0.6)
                        duration = float(getattr(ln, 'audio_duration', 0.0) or 0.0)
                        return (0, len(txt) / (duration - pauses) if (duration - pauses) > 0 else 0.0)
                    except Exception:
                        if i < len(self.ver_analysis_results):
                            return (0, float(self.ver_analysis_results[i].get('cps') or 0.0))
                        return (1, 0.0)
                if col_id == 'status':
                    # Prefer Line audio_status or derived status
                    try:
                        st = getattr(ln, 'audio_status', None)
                        if st:
                            return (0, st)
                    except Exception:
                        pass
                    if i < len(self.ver_analysis_results):
                        stat = self.ver_analysis_results[i].get('display_status') or ''
                        return (0, stat) if stat else (1, '')
                    return (1, '')
                if col_id == 'format':
                    try:
                        fmt = getattr(ln, 'audio_format', '') or ''
                        if fmt:
                            return (0, fmt.lower())
                    except Exception:
                        pass
                    if i < len(self.ver_analysis_results):
                        ext = (self.ver_analysis_results[i].get('ext') or '').lower()
                        return (0, ext) if ext else (1, '')
                    return (1, '')
                if col_id == 'audio_file':
                    try:
                        afn = getattr(ln, 'audio_filename', '')
                        if afn:
                            return (0, str(Path(getattr(self, 'app').audio_dir or Path('.')) / afn))
                    except Exception:
                        pass
                    if i < len(self.ver_analysis_results):
                        p = self.ver_analysis_results[i].get('path')
                        return (0, str(p)) if p else (1, '')
                    return (1, '')
            except Exception as e:
                print(f"[ERROR] Sort key_fn error for col {col_id}: {e}")
                return (1, '')  # None wartości na koniec
            
            # Domyślnie None wartości na koniec
            return (1, '')

        indexed = list(enumerate(self.app.lines))
        try:
            indexed.sort(key=key_fn, reverse=not asc)
        except TypeError as e:
            print(f"[ERROR] Sort failed for col {col_id}: {e}")
            return
            
        # reorder app.lines accordingly
        self.app.lines = [ln for _, ln in indexed]
        # reorder ver_analysis_results if present
        try:
            self.ver_analysis_results = [self.ver_analysis_results[i] for i, _ in indexed if i < len(self.ver_analysis_results)]
        except Exception:
            pass
        # refresh UI
        try:
            self._refresh_verification_view()
        except Exception:
            pass

    

    def set_preview(self, lines_to_show: list[Line]):
        """
        Wypełnia tabelę danymi.
        Argument lines_to_show to lista obiektów `Line`.
        """
        print(f"[SET_PREVIEW] START: {len(lines_to_show) if lines_to_show else 0} linii")
        preserved_index = self.app.selected_line_index

        # Wyczyść tabelę
        for item in self.tree.get_children():
            self.tree.delete(item)

        search_term = self.search_entry.get().lower()

        # Przygotuj dane do wstawienia
        # Jeśli w przyszłości lines_to_show będzie listą słowników/obiektów,
        # tutaj trzeba będzie dostosować mapowanie na kolumny.

        item_to_select = None

        for i, item in enumerate(lines_to_show):
            # item is expected to be a Line object; fall back to string if necessary
            if isinstance(item, str):
                line_text = item
                line_obj = None
            else:
                line_obj = item
                line_text = (line_obj.text or '') if line_obj is not None else ''

            # derive content text based on view mode
            try:
                mode = self.app.view_mode.get()
                if line_obj is not None:
                    if mode == 'Napisy':
                        content_text = (line_obj.text or '').lower()
                    elif mode == 'TTS':
                        content_text = (line_obj.tts_text or '').lower()
                    else:
                        content_text = (line_obj.text or '').lower()
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
                        txt = (line_obj.tts_text or '').strip('.?!')
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
            try:
                # Jeśli filtr similarity jest ustawiony, pominąć linie bez weryfikacji
                if (f.get('min_sim') is not None and f.get('min_sim') != '') or (f.get('max_sim') is not None and f.get('max_sim') != ''):
                    # require a transcribed text or audio file to compute similarity
                    if line_obj is None and (not ar or ar.get('path') is None):
                        continue
                sim_val = float(getattr(line_obj, 'audio_similarity', 0.0) or 0.0) if line_obj else float(ar.get('similarity') or 0.0 if ar else 0.0)
                if f.get('min_sim') is not None and f.get('min_sim') != '' and sim_val < float(f.get('min_sim')):
                    continue
                if f.get('max_sim') is not None and f.get('max_sim') != '' and sim_val > float(f.get('max_sim')):
                    continue
            except Exception:
                pass
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

            line_nr = i + 1

            # Budowanie wartości dla wiersza zgodnie z self.columns_config
            row_values = []
            for col in self.columns_config:
                col_id = col["id"]
                if col_id == "line_nr":
                    row_values.append(f"{line_nr:06d}")
                elif col_id == "content":
                    if line_obj is not None:
                        if self.app.view_mode.get() == 'TTS':
                            row_values.append(line_obj.tts_text or '')
                        else:
                            row_values.append(line_obj.text or '')
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
                    if i in [85, 86, 87, 88, 89]:  # Log critical rows
                        print(f"[SET_PREVIEW] L{i+1}: duration={row_values[col_pos['duration']]}, line_obj.audio_duration={getattr(line_obj, 'audio_duration', 'BRAK') if line_obj else 'NO_OBJ'}")
                if 'cps' in col_pos:
                    try:
                        cps_val = 0.0
                        if line_obj is not None:
                            txt = (line_obj.tts_text or '').strip('.?!')
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
                    similarity_val = float(getattr(line_obj, 'audio_similarity', 0.0) or 0.0) if line_obj else (float(self.ver_analysis_results[i].get('similarity', 0.0) or 0.0) if i < len(self.ver_analysis_results) else 0.0)
                    row_values[col_pos['similarity']] = f"{similarity_val:.0%}" if similarity_val > 0 else '-'
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

            # Sprawdzenie czy ten wiersz ma być zaznaczony (przy odświeżaniu widoku)
            if preserved_index is not None and line_nr == preserved_index + 1:
                item_to_select = item_id

        # Przywrócenie zaznaczenia
        if item_to_select:
            self.tree.selection_set(item_to_select)
            self.tree.see(item_to_select)
        
        # NOWE: Jeśli użytkownik miał zaznaczenie (selected_line_indices jest nie puste),
        # przywracamy je w nowej tabeli JEŚLI wiersze są dostępne
        if self.selected_line_indices:
            print(f"[SET_PREVIEW] Przywracam zaznaczenie: {self.selected_line_indices}")
            items_to_select = []
            for item_id in self.tree.get_children():
                try:
                    item_vals = self.tree.item(item_id, "values")
                    line_nr = int(item_vals[0])
                    if line_nr - 1 in self.selected_line_indices:
                        items_to_select.append(item_id)
                except (ValueError, IndexError):
                    pass
            
            if items_to_select:
                print(f"[SET_PREVIEW] Znaleziono {len(items_to_select)} rów do zaznaczenia")
                self.tree.selection_set(*items_to_select)
                self.tree.see(items_to_select[0])
            else:
                print(f"[SET_PREVIEW] Nie znaleziono wierszy do zaznaczenia")
                self.app.selected_line_index = None
        else:
            self.app.selected_line_index = None
            self.update_audio_buttons_state()

    def on_tree_select(self, event):
        """Obsługa wyboru wiersza w tabeli - aktualizuje selected_line_indices."""
        selected_items = self.tree.selection()
        print(f"[TREE_SELECT] selected_items={len(selected_items) if selected_items else 0}")
        
        if not selected_items:
            self.app.selected_line_index = None
            self.selected_line_indices = []
            self.update_audio_buttons_state()
            return

        # Pobierz wszystkie zaznaczone elementy
        selected_indices = []
        for item_id in selected_items:
            item_values = self.tree.item(item_id, "values")
            try:
                line_nr_str = item_values[0]
                line_nr = int(line_nr_str)
                selected_indices.append(line_nr - 1)
            except (ValueError, IndexError):
                continue

        # Ustaw first selected jako primary
        if selected_indices:
            self.app.selected_line_index = selected_indices[0]
            self.selected_line_indices = selected_indices
            print(f"[TREE_SELECT] Aktualizuję zaznaczenie na {len(selected_indices)} wierszy")
        else:
            self.app.selected_line_index = None
            self.selected_line_indices = []

        self.update_audio_buttons_state()

    def _start_inline_edit(self, event):
        """Uruchamia edycję inline tekstu w tabeli przy Ctrl+Click."""
        # Sprawdzenie czy jesteśmy w edytowalnym trybie
        mode = self.app.view_mode.get()
        if mode == "Oryginał":
            return
        
        # Znajdź wiersz i kolumnę pod kursorem
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        
        if not item or not col:
            return
        
        # Pobierz indeks kolumny
        try:
            col_idx = int(col[1]) - 1  # col jest w formacie '#1', '#2' itd.
        except (ValueError, IndexError):
            return
        
        # Sprawdzenie czy to kolumna "content"
        if col_idx >= len(self.columns_config):
            return
        
        col_id = self.columns_config[col_idx]["id"]
        if col_id != "content":
            return
        
        # Pobierz numer linii
        try:
            item_values = self.tree.item(item, "values")
            line_nr_str = item_values[0]
            line_idx = int(line_nr_str) - 1
        except (ValueError, IndexError):
            return
        
        # Pobierz aktualny tekst
        try:
            current_text = item_values[1] or ""
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
        self.app.apply_patterns()
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
        if not self.ver_analysis_results:
            for i, line in enumerate(self.app.lines):
                self.ver_analysis_results.append({
                    'id': i + 1,
                    'text': line.tts_text,
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

        lines_texts = [l.tts_text for l in self.app.lines]
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
        print(f"[REFRESH_VIEW] Aktualizuję {len(self.selected_line_indices)} wierszy")
        # Mapowanie line_nr -> item_id w tabeli
        line_nr_to_item = {}
        for item_id in self.tree.get_children():
            item_vals = self.tree.item(item_id, "values")
            try:
                line_nr = int(item_vals[0])
                line_nr_to_item[line_nr] = item_id
            except (ValueError, IndexError):
                pass
        
        # Aktualizuj wartości dla każdego zweryfikowanego wiersza
        col_pos = {c['id']: idx for idx, c in enumerate(self.columns_config)}
        
        updated_count = 0
        for line_idx in self.selected_line_indices:
            if line_idx < 0 or line_idx >= len(self.app.lines):
                continue
            
            line_nr = line_idx + 1
            item_id = line_nr_to_item.get(line_nr)
            if not item_id:
                continue
            
            line_obj = self.app.lines[line_idx]
            row_values = list(self.tree.item(item_id, "values"))
            
            try:
                # Update duration
                if 'duration' in col_pos:
                    duration_val = float(getattr(line_obj, 'audio_duration', 0.0) or 0.0)
                    row_values[col_pos['duration']] = f"{duration_val:.2f}" if duration_val > 0 else '-'
                
                # Update CPS
                if 'cps' in col_pos:
                    try:
                        txt = (line_obj.tts_text or '').strip('.?!')
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
                    row_values[col_pos['similarity']] = f"{similarity_val:.0%}" if similarity_val > 0 else '-'
                
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
                
            except Exception as e:
                pass
        
        print(f"[REFRESH_VIEW] Zaktualizowano {updated_count} wierszy")
        
        # Przywróć zaznaczenie
        try:
            items_to_select = []
            for item_id in self.tree.get_children():
                item_vals = self.tree.item(item_id, "values")
                try:
                    line_nr = int(item_vals[0])
                    if line_nr - 1 in self.selected_line_indices:
                        items_to_select.append(item_id)
                except (ValueError, IndexError):
                    pass
            
            if items_to_select:
                self.tree.selection_set(*items_to_select)
                self.tree.see(items_to_select[0])
        except Exception as e:
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
            if mode == 'Napisy':
                return self.app.lines[idx].text
            elif mode == 'TTS':
                return self.app.lines[idx].tts_text
            else:
                return self.app.lines[idx].text or ''
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
            self._refresh_verification_view()
        except Exception:
            pass

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
        Sprawdza obecny stan przycisków dla wielu zaznaczonych wierszy.
        """
        has_selection = len(self.selected_line_indices) > 0
        audio_dir_set = self.app.audio_dir is not None and self.app.audio_dir.is_dir()
        project_loaded = self.app.current_project_path is not None
        lines_processed = bool(self.app.lines)

        files_exist = False
        status_msg = "Audio: ---"

        if has_selection and audio_dir_set:
            # Sprawdź pierwszy zaznaczony
            identifier = str(self.app.selected_line_index + 1)
            found_files = self._find_audio_files(identifier)
            files_exist = bool(found_files)

            if found_files:
                status_msg = f"Audio: znaleziono {len(found_files)}"
                self.first_found_audio = found_files[0][0]
            else:
                status_msg = "Audio: brak"
                self.first_found_audio = None

        # Aktualizacja statusu
        if hasattr(self.app, 'set_audio_status'):
            self.app.set_audio_status(status_msg)

        gen_state = "normal" if has_selection and audio_dir_set and project_loaded and lines_processed else "disabled"
        verify_state = "normal" if has_selection and audio_dir_set and project_loaded else "disabled"
        del_state = "normal" if has_selection and audio_dir_set and files_exist else "disabled"

        # Aktualizuj buttony (tylko jeśli stan się zmienił)
        if self.generate_button.cget("state") != gen_state:
            self.generate_button.configure(state=gen_state)

        if self.verify_button.cget("state") != verify_state:
            self.verify_button.configure(state=verify_state)

        if self.delete_all_button.cget("state") != del_state:
            self.delete_all_button.configure(state=del_state)

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

    def generate_selected_dialogs(self):
        """Generuje audio dla wszystkich zaznaczonych wierszy."""
        if not self.selected_line_indices or not self.app.audio_dir:
            return

        lines_to_gen = []
        for idx in self.selected_line_indices:
            try:
                line_no = idx + 1
                text = self.app.lines[idx].tts_text
                lines_to_gen.append((str(line_no), text))
            except (IndexError, ValueError):
                continue

        if not lines_to_gen:
            messagebox.showwarning("Brak danych", "Nie można wygenerować audio dla zaznaczonych linii.", parent=self)
            return

        tts_model = self.app._get_active_tts_model_name()
        if not tts_model:
            messagebox.showerror("Błąd", "Brak modelu TTS.", parent=self)
            return

        from audio.generation_manager import GenerationManager, GenerationJob
        job = GenerationJob(
            project_path=f"ZAZNACZONYCH ({len(lines_to_gen)}) - {self.app.current_project_path.name}",
            audio_dir=self.app.audio_dir,
            lines_to_generate=lines_to_gen,
            tts_model_name=tts_model,
            tts_config=self.app._gather_tts_config(),
            converter_config=self.app._gather_converter_config()
        )

        def _on_generate(identifier: str, path: str):
            try:
                idx = int(identifier) - 1
                if 0 <= idx < len(self.app.lines):
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
        print(f"[VERIFY_SEL] START: selected_indices={self.selected_line_indices}, audio_dir={self.app.audio_dir}")
        if not self.selected_line_indices or not self.app.audio_dir:
            print(f"[VERIFY_SEL] Błąd: selected_indices={bool(self.selected_line_indices)}, audio_dir={bool(self.app.audio_dir)}")
            return

        if self.ver_running:
            messagebox.showinfo("Weryfikacja", "Weryfikacja jest już w toku.", parent=self)
            return

        if VerificationManager is None:
            messagebox.showerror("Błąd", "Brak VerificationManager.", parent=self)
            return

        self.ver_running = True
        
        # Inicjalizuj ver_analysis_results z całą listą linii
        if not self.ver_analysis_results or len(self.ver_analysis_results) < len(self.app.lines):
            self.ver_analysis_results = []
            for i, line in enumerate(self.app.lines):
                self.ver_analysis_results.append({
                    'id': i + 1,
                    'text': line.tts_text if line.tts_text else '',
                    'duration': 0.0,
                    'cps': 0.0,
                    'raw_status': 'PENDING',
                    'path': None,
                    'ext': '',
                    'display_status': 'PENDING'
                })
        
        self.app.set_status(f"Weryfikacja {len(self.selected_line_indices)} linii...")
        print(f"[VERIFY_SEL] Uruchamianie wątku dla indeksów: {self.selected_line_indices}")

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

            for line_idx in selected_indices:
                if line_idx < 0 or line_idx >= len(self.app.lines):
                    continue

                try:
                    line = self.app.lines[line_idx]
                    line_id = line_idx + 1  # 1-based ID
                    
                    # Weryfikuj pojedynczą linię
                    result = VerificationManager.verify_line(
                        line=line,
                        audio_dir=audio_dir,
                        line_id=line_id,
                        ffprobe_path=ffprobe,
                        ignore_short=True,
                        verify_duration=True
                    )
                    results[str(line_id)] = result
                except Exception as e:
                    results[str(line_idx + 1)] = {
                        'id': line_idx + 1,
                        'text': self.app.lines[line_idx].tts_text if line_idx < len(self.app.lines) else '',
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
        line_nums = []
        for idx in self.selected_line_indices:
            line_num = idx + 1
            identifier = str(line_num)
            found_files = self._find_audio_files(identifier)
            if found_files:
                files_to_delete.extend(found_files)
                line_nums.append(line_num)

        if not files_to_delete:
            messagebox.showinfo("Info", "Nie znaleziono plików audio do usunięcia.", parent=self)
            return

        if not messagebox.askyesno("Potwierdź",
                                   f"Czy na pewno usunąć WSZYSTKIE ({len(files_to_delete)}) pliki dla {len(line_nums)} zaznaczonych linii?",
                                   parent=self):
            return

        self.stop_audio()
        for file_path, _ in files_to_delete:
            try:
                os.remove(file_path)
            except Exception:
                pass
        self.update_audio_buttons_state()


# --- Process entry function (runs in separate process) ---
def _verification_process_entry(audio_dir: str, lines_texts: list, out_file: str, ffprobe_path: str, force_refresh: bool, ignore_short: bool, worker_idx: int = 0, total_workers: int = 1):
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

    for i, text in enumerate(lines_texts):
        # distribute work among workers: only process indices matching this worker
        if total_workers and (i % total_workers) != worker_idx:
            continue
        ident = str(i + 1)
        tts = (text or '').strip()
        entry = {'id': i+1, 'text': tts, 'duration': 0.0, 'cps': 0.0, 'raw_status': 'PENDING', 'path': None, 'ext': '', 'display_status': 'PENDING'}
        if not tts:
            results[ident] = entry
            write_atomic(results)
            continue

        # find file
        audio_file = None
        found_ext = ''
        candidates = [
            (audio_dir_p / f"output1 ({ident}).wav", 'wav'),
            (audio_dir_p / f"output1 ({ident}).mp3", 'mp3'),
            (audio_dir_p / 'ready' / f"output1 ({ident}).ogg", 'ogg'),
            (audio_dir_p / 'ready' / f"output1 ({ident}).mp3", 'mp3')
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