import customtkinter as ctk
import os
import wave
import subprocess
import contextlib
import threading
import time
import shutil
import json
from tkinter import messagebox
from pathlib import Path

from audio.audio_renamer import AudioRenameWindow

try:
    from mutagen.mp3 import MP3

    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False


class AudioVerificationWindow(ctk.CTkToplevel):
    def __init__(self, app, audio_dir, subtitles):
        super().__init__(app)
        self.app = app
        self.audio_dir = Path(audio_dir)
        self.subtitles = subtitles

        # Stan procesu
        self.running = False
        self.paused = False
        self.stop_event = threading.Event()
        self.current_index = 0

        # Wyniki
        self.analysis_results = []
        self.error_details = {}
        self.cache_data = {}

        # Audio process
        self.current_audio_process = None
        self.ffplay_path = shutil.which("ffplay")
        self.ffprobe_path = shutil.which("ffprobe")

        self.avg_cps = 15.0
        self.calibration_done = False

        # Cache setup
        self.cache_file = None
        if self.app.loaded_path:
            self.cache_file = self.app.loaded_path.with_suffix(".cps_cache.json")

        self.title(f"Weryfikacja audio ({len(subtitles)} linii)")
        self.geometry("1300x850")

        self.lift()
        self.focus_force()
        self.after(100, self.lift)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # --- GŁÓWNY GRID ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # =====================================================================
        # 1. PANEL STEROWANIA
        # =====================================================================
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.top_frame.grid_columnconfigure(2, weight=1)

        # -- Sekcja Przycisków (Lewa) --
        self.btn_frame = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.btn_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Jeden główny przycisk akcji (Start/Wznów)
        self.btn_action = ctk.CTkButton(self.btn_frame, text="Rozpocznij Analizę", fg_color="green",
                                        hover_color="darkgreen",
                                        command=self.on_action_click, width=160)
        self.btn_action.pack(side="left", padx=5)

        self.btn_stop = ctk.CTkButton(self.btn_frame, text="Zatrzymaj", fg_color="gray", hover_color="gray",
                                      command=self.stop_analysis, state="disabled", width=100)
        self.btn_stop.pack(side="left", padx=5)

        # Button: Usuń błędne
        self.btn_del_errors = ctk.CTkButton(self.btn_frame, text="🗑 Usuń błędne", fg_color="darkred",
                                            hover_color="#800000",
                                            command=self.delete_all_errors_action, width=120)
        self.btn_del_errors.pack(side="left", padx=20)

        # -- Opcje sterowania błędami --
        self.opts_frame = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.opts_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        self.var_stop_on_error = ctk.BooleanVar(value=True)
        self.cb_stop_on_error = ctk.CTkCheckBox(self.opts_frame, text="Zatrzymaj na błędzie",
                                                variable=self.var_stop_on_error)
        self.cb_stop_on_error.pack(anchor="w")

        self.var_force_refresh = ctk.BooleanVar(value=False)
        self.cb_force_refresh = ctk.CTkCheckBox(self.opts_frame, text="Wymuś odświeżenie (bez cache)",
                                                variable=self.var_force_refresh)
        self.cb_force_refresh.pack(anchor="w")

        # -- Filtry i Suwaki (Prawa) --
        self.filters_frame = ctk.CTkFrame(self.top_frame)
        self.filters_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)

        ctk.CTkLabel(self.filters_frame, text="Tolerancja CPS (Auto-kalibracja po 20 plikach)",
                     font=("", 11, "bold")).grid(row=0, column=0, columnspan=4, pady=(2, 0))

        self.lbl_min_cps = ctk.CTkLabel(self.filters_frame, text="Min: 3.0")
        self.lbl_min_cps.grid(row=1, column=0, padx=5)
        self.slider_min_cps = ctk.CTkSlider(self.filters_frame, from_=0.1, to=20.0, number_of_steps=199,
                                            command=self.on_slider_change)
        self.slider_min_cps.set(3.0)
        self.slider_min_cps.grid(row=1, column=1, padx=5, sticky="ew")

        self.lbl_max_cps = ctk.CTkLabel(self.filters_frame, text="Max: 30.0")
        self.lbl_max_cps.grid(row=1, column=2, padx=5)
        self.slider_max_cps = ctk.CTkSlider(self.filters_frame, from_=10.0, to=60.0, number_of_steps=250,
                                            command=self.on_slider_change)
        self.slider_max_cps.set(30.0)
        self.slider_max_cps.grid(row=1, column=3, padx=5, sticky="ew")

        # Filtry widoku
        self.filter_opts_frame = ctk.CTkFrame(self.filters_frame, fg_color="transparent")
        self.filter_opts_frame.grid(row=2, column=0, columnspan=4, sticky="ew")

        self.var_ignore_short = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.filter_opts_frame, text="Ignoruj < 5 zn.", variable=self.var_ignore_short,
                        command=self.refresh_list_view).pack(side="left", padx=10)

        self.var_show_only_errors = ctk.BooleanVar(value=True)
        self.sw_filter = ctk.CTkSwitch(self.filter_opts_frame, text="Tylko problemy",
                                       variable=self.var_show_only_errors, command=self.refresh_list_view)
        self.sw_filter.pack(side="right", padx=10)

        # =====================================================================
        # 2. STATUS I POSTĘP
        # =====================================================================
        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))

        self.progress_bar = ctk.CTkProgressBar(self.status_frame)
        self.progress_bar.pack(fill="x", padx=5, pady=5)
        self.progress_bar.set(0)

        self.lbl_status = ctk.CTkLabel(self.status_frame, text="Gotowy. Naciśnij 'Rozpocznij Analizę'.",
                                       font=("", 12, "bold"))
        self.lbl_status.pack(side="left", padx=10, pady=2)

        self.lbl_stats = ctk.CTkLabel(self.status_frame, text="--", font=("", 12))
        self.lbl_stats.pack(side="right", padx=10, pady=2)

        # =====================================================================
        # 3. LISTA WYNIKÓW
        # =====================================================================
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

        headers = ["ID", "Tekst (fragment)", "Czas", "CPS", "Status", "Format", "Akcje"]
        self.scroll_frame.grid_columnconfigure(1, weight=1)

        for idx, h in enumerate(headers):
            ctk.CTkLabel(self.scroll_frame, text=h, font=("", 12, "bold")).grid(row=0, column=idx, padx=5, pady=5,
                                                                                sticky="w")

        if not self.ffprobe_path and not MUTAGEN_AVAILABLE:
            self.lbl_status.configure(text="Ostrzeżenie: Brak ffprobe! Analiza MP3 może nie działać.",
                                      text_color="orange")

    def on_close(self):
        if self.running:
            self.stop_analysis()
        self.stop_audio()
        self.destroy()

    def stop_audio(self):
        if self.current_audio_process:
            if self.current_audio_process.poll() is None:
                self.current_audio_process.terminate()
            self.current_audio_process = None

    def stop_analysis(self):
        """Pełne zatrzymanie przez użytkownika."""
        if self.running:
            self.stop_event.set()
            self.lbl_status.configure(text="Zatrzymywanie...")
            self.btn_stop.configure(state="disabled", fg_color="gray")
            self.paused = False
            # Reset przycisku na start
            self.btn_action.configure(text="Rozpocznij Analizę", state="normal", fg_color="green")

    # --- Cache Logic ---
    def _load_cache(self):
        if self.cache_file and self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache_data = json.load(f)
            except Exception:
                self.cache_data = {}

    def _save_cache(self):
        if self.cache_file:
            try:
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.cache_data, f, ensure_ascii=False)
            except Exception:
                pass

    # --- Sterowanie Procesem ---

    def on_action_click(self):
        """Obsługa głównego przycisku Start/Wznów."""
        if self.paused:
            # Jeśli zapauzowany -> Wznów
            self.resume_analysis()
        else:
            # Jeśli nie działa -> Start od nowa
            if not self.running:
                self.start_analysis_fresh()

    def start_analysis_fresh(self):
        """Rozpoczyna analizę od początku."""
        self.current_index = 0
        self.analysis_results = []
        self.error_details = {}
        self.calibration_done = False
        self.paused = False

        # Reset UI listy
        for widget in self.scroll_frame.winfo_children():
            if int(widget.grid_info()["row"]) > 0:
                widget.destroy()

        self._start_worker()

    def resume_analysis(self):
        """Wznawia analizę od ostatniego indeksu."""
        self.paused = False
        self._start_worker()

    def _start_worker(self):
        self.running = True
        self.stop_event.clear()

        # UI Update
        self.btn_action.configure(text="Analiza w toku...", state="disabled", fg_color="gray")
        self.btn_stop.configure(state="normal", fg_color="red")
        self.cb_force_refresh.configure(state="disabled")
        self.lbl_status.configure(text="Analiza w toku...", text_color=["black", "white"])

        thread = threading.Thread(target=self._analysis_worker, daemon=True)
        thread.start()

    # --- Worker ---

    def _analysis_worker(self):
        force_refresh = self.var_force_refresh.get()
        if not force_refresh and not self.cache_data:
            self._load_cache()
        elif force_refresh and not self.analysis_results:
            if self.current_index == 0:
                self.cache_data = {}

        total_lines = len(self.subtitles)

        rolling_chars = 0
        rolling_duration = 0
        calibration_count = 0

        last_update_time = time.time()

        for i in range(self.current_index, total_lines):
            if self.stop_event.is_set():
                break

            text = self.subtitles[i]
            ident = str(i + 1)
            text_clean = text.strip()

            if not text_clean:
                self.current_index = i + 1
                continue

            # --- FIND FILE ---
            audio_file = None
            found_ext = ""

            paths_to_check = [
                (self.audio_dir / f"output1 ({ident}).wav", "wav"),
                (self.audio_dir / f"output1 ({ident}).mp3", "mp3"),
                (self.audio_dir / "ready" / f"output1 ({ident}).ogg", "ogg"),
                (self.audio_dir / "ready" / f"output1 ({ident}).mp3", "mp3")
            ]

            cached_entry = self.cache_data.get(ident)
            cache_hit = False
            duration = 0.0
            error_msg = None

            if not force_refresh and cached_entry:
                if cached_entry.get("text") == text_clean:
                    c_path = cached_entry.get("path")
                    if c_path and os.path.exists(c_path):
                        audio_file = Path(c_path)
                        found_ext = cached_entry.get("ext", "")
                        duration = cached_entry.get("duration", 0.0)
                        error_msg = cached_entry.get("error")
                        cache_hit = True

            if not cache_hit:
                for p, ext in paths_to_check:
                    if p.exists():
                        audio_file = p
                        found_ext = ext
                        break

                if audio_file:
                    duration, error_msg = self.get_audio_duration(audio_file, found_ext)

            # --- INTERPRETATION ---
            cps = 0.0
            raw_status = "MISSING"

            if audio_file:
                if duration < 0:
                    raw_status = "ERROR"
                    self.error_details[ident] = f"{found_ext.upper()}: {error_msg}"
                    duration = 0.0
                elif duration == 0.0:
                    raw_status = "EMPTY"
                else:
                    raw_status = "OK"
                    char_count = len(text_clean)
                    cps = char_count / duration

                    self.cache_data[ident] = {
                        "text": text_clean,
                        "duration": duration,
                        "path": str(audio_file),
                        "ext": found_ext,
                        "error": None
                    }

                    rolling_chars += char_count
                    rolling_duration += duration
                    calibration_count += 1
            else:
                self.cache_data[ident] = {
                    "text": text_clean, "duration": 0, "path": None, "error": "Missing"
                }

            result_item = {
                "id": int(ident),
                "text": text,
                "duration": duration,
                "cps": cps,
                "raw_status": raw_status,
                "path": audio_file,
                "ext": found_ext
            }
            self.analysis_results.append(result_item)

            self.current_index = i + 1

            # --- AUTO-CALIBRATION ---
            if not self.calibration_done and calibration_count >= 20:
                self.calibration_done = True
                curr_avg = rolling_chars / rolling_duration if rolling_duration > 0 else 15.0
                self.avg_cps = curr_avg
                self.app.after(0, lambda a=curr_avg: self._apply_calibration(a))

            # --- ERROR CHECK & STOP ---
            is_error = self._check_if_error(result_item)

            if is_error and self.var_stop_on_error.get():
                self.paused = True
                self.app.after(0, lambda: self._handle_pause_on_error(result_item))
                break

            current_time = time.time()
            if (i % 20 == 0) or (current_time - last_update_time > 0.1):
                progress = self.current_index / total_lines
                self.app.after(0, lambda p=progress, c=self.current_index: self._update_progress_ui(p, c, total_lines))
                last_update_time = current_time

        # --- END OF LOOP ---
        self._save_cache()

        if not self.paused:
            self.app.after(0, lambda: self._finalize_ui(self.current_index))

    def _check_if_error(self, item):
        if item["raw_status"] != "OK":
            return True

        min_cps = self.slider_min_cps.get()
        max_cps = self.slider_max_cps.get()
        ignore_short = self.var_ignore_short.get()

        if ignore_short and len(item["text"]) < 5:
            return False

        if item["cps"] < min_cps or item["cps"] > max_cps:
            return True

        return False

    def _apply_calibration(self, avg):
        new_min = max(0.1, avg - 4.0)
        new_max = avg + 8.0

        self.slider_min_cps.set(new_min)
        self.slider_max_cps.set(new_max)

        self.lbl_min_cps.configure(text=f"Min: {new_min:.1f}")
        self.lbl_max_cps.configure(text=f"Max: {new_max:.1f}")
        self.refresh_list_view()

    def _handle_pause_on_error(self, error_item):
        self.running = False
        self.btn_stop.configure(state="disabled", fg_color="gray")

        # Zmiana przycisku na "Wznów"
        self.btn_action.configure(text="Wznów", state="normal", fg_color="#1f6aa5")

        self.cb_force_refresh.configure(state="normal")

        err_txt = f"Zatrzymano na błędzie w linii {error_item['id']}!"
        self.lbl_status.configure(text=err_txt, text_color="red")

        self.refresh_list_view()

    def _update_progress_ui(self, progress, current, total):
        self.progress_bar.set(progress)
        self.lbl_status.configure(text=f"Analiza: {current}/{total}...")

    def _finalize_ui(self, total_processed):
        if self.paused: return

        self.running = False
        self.btn_stop.configure(state="disabled", fg_color="gray")
        # Reset na Start
        self.btn_action.configure(text="Rozpocznij Analizę", state="normal", fg_color="green")
        self.cb_force_refresh.configure(state="normal")
        self.progress_bar.set(1.0)

        if self.stop_event.is_set():
            self.lbl_status.configure(text="Analiza przerwana przez użytkownika.", text_color="orange")
        else:
            self.lbl_status.configure(text="Analiza zakończona.", text_color="green")

        self.refresh_list_view()

    # --- Wyświetlanie listy ---

    def on_slider_change(self, value):
        self.lbl_min_cps.configure(text=f"Min: {self.slider_min_cps.get():.1f}")
        self.lbl_max_cps.configure(text=f"Max: {self.slider_max_cps.get():.1f}")
        self.refresh_list_view()

    def refresh_list_view(self, *args):
        for widget in self.scroll_frame.winfo_children():
            if int(widget.grid_info()["row"]) > 0:
                widget.destroy()

        min_cps = self.slider_min_cps.get()
        max_cps = self.slider_max_cps.get()
        ignore_short = self.var_ignore_short.get()
        show_errors_only = self.var_show_only_errors.get()

        filtered_items = []
        suspicious_count = 0

        for item in self.analysis_results:
            status = "OK"
            is_error = False

            if item["raw_status"] != "OK":
                status = item["raw_status"]
                is_error = True
                if status == "MISSING" or status == "USUNIĘTO":
                    item["display_status"] = "BRAK/USUN."
                else:
                    item["display_status"] = status
            else:
                cps = item["cps"]
                text_len = len(item["text"])

                if ignore_short and text_len < 5:
                    status = "SHORT"
                    is_error = False
                else:
                    if cps < min_cps:
                        status = f"ZA WOLNO (<{min_cps:.1f})"
                        is_error = True
                    elif cps > max_cps:
                        status = f"ZA SZYBKO (>{max_cps:.1f})"
                        is_error = True
                item["display_status"] = status

            item["is_error"] = is_error
            if is_error: suspicious_count += 1

            if show_errors_only:
                if is_error: filtered_items.append(item)
            else:
                filtered_items.append(item)

        self.lbl_stats.configure(text=f"Błędy: {suspicious_count} | Przeanalizowano: {len(self.analysis_results)}")

        LIMIT = 25
        row = 1

        if not filtered_items:
            ctk.CTkLabel(self.scroll_frame, text="Brak wyników do wyświetlenia.").grid(row=row, column=1)
            return

        for item in filtered_items[:LIMIT]:
            color = "white"
            st = item["display_status"]
            if "SZYBKO" in st or "WOLNO" in st:
                color = "orange"
            elif st in ["ERROR", "MISSING", "EMPTY", "BRAK/USUN.", "USUNIĘTO"]:
                color = "red"
            elif st == "OK":
                color = "green"
            elif st == "SHORT":
                color = "gray"

            ctk.CTkLabel(self.scroll_frame, text=str(item["id"])).grid(row=row, column=0, sticky="w", padx=5)

            txt = (item["text"][:25] + '..') if len(item["text"]) > 25 else item["text"]
            ctk.CTkLabel(self.scroll_frame, text=txt).grid(row=row, column=1, sticky="w", padx=5)

            dur = f"{item['duration']:.2f}s" if item["duration"] > 0 else "-"
            ctk.CTkLabel(self.scroll_frame, text=dur).grid(row=row, column=2, sticky="w", padx=5)

            cps_val = f"{item['cps']:.1f}" if item["duration"] > 0 else "-"
            ctk.CTkLabel(self.scroll_frame, text=cps_val).grid(row=row, column=3, sticky="w", padx=5)

            ctk.CTkLabel(self.scroll_frame, text=st, text_color=color).grid(row=row, column=4, sticky="w", padx=5)

            fmt = item["ext"].upper() if item["ext"] else "-"
            ctk.CTkLabel(self.scroll_frame, text=fmt).grid(row=row, column=5, sticky="w", padx=5)

            # Action Buttons Frame
            act_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            act_frame.grid(row=row, column=6, padx=5, pady=2)

            # 1. Odtwarzanie
            if item["path"]:
                ctk.CTkButton(act_frame, text="▶", width=30, height=24,
                              command=lambda p=item["path"]: self.play_audio(p)).pack(side="left", padx=2)

            # 2. Naprawa (Dopasuj) - otwiera AudioRenameWindow
            # UWAGA: Używa nowej nazwy okna AudioRenameWindow
            ctk.CTkButton(act_frame, text="🛠", width=30, height=24, fg_color="#E0A800", text_color="black",
                          hover_color="#C09000",
                          command=lambda i=item["id"]: self.open_rename_window(i)).pack(side="left", padx=2)

            # 3. Usuwanie (Kosz)
            if item["path"] or item["raw_status"] == "OK":
                ctk.CTkButton(act_frame, text="🗑", width=30, height=24, fg_color="darkred", hover_color="red",
                              command=lambda i=item["id"]: self.delete_audio(i)).pack(side="left", padx=2)

            row += 1

        if len(filtered_items) > LIMIT:
            ctk.CTkLabel(self.scroll_frame, text=f"... {len(filtered_items) - LIMIT} więcej ...").grid(row=row,
                                                                                                       column=1)

    # --- Actions ---

    def delete_all_errors_action(self):
        """Usuwa wszystkie pliki oznaczone jako błąd (czerwony/pomarańczowy)."""
        items_to_delete = [item for item in self.analysis_results if item.get("is_error", False) and item.get("path")]

        if not items_to_delete:
            messagebox.showinfo("Info", "Brak błędnych plików audio do usunięcia.", parent=self)
            return

        count = len(items_to_delete)
        if not messagebox.askyesno("Potwierdzenie",
                                   f"Czy na pewno chcesz usunąć {count} plików audio oznaczonych jako błędne?",
                                   parent=self):
            return

        deleted_count = 0
        for item in items_to_delete:
            if self.delete_audio(item["id"], refresh_ui=False):
                deleted_count += 1

        self.refresh_list_view()
        messagebox.showinfo("Sukces", f"Usunięto {deleted_count} plików.", parent=self)

    def open_rename_window(self, ident):
        """Otwiera AudioRenameWindow dla danej linii."""
        start_index = ident - 1

        try:
            win = None
            # Opcja 1: Jeśli zaimportowano klasę bezpośrednio
            if AudioRenameWindow:
                win = AudioRenameWindow(self.app, self.audio_dir)

            # Opcja 2: Użycie metody z app (jeśli klasa niezaimportowana)
            elif hasattr(self.app, 'open_audio_rename_window'):
                # Ta metoda prawdopodobnie tworzy okno i zapisuje referencję
                self.app.open_audio_rename_window()
                # Próbujemy znaleźć referencję do otwartego okna
                # (Zależy to od implementacji w studio.py, ale często jest to self.app.audio_rename_window)
                if hasattr(self.app, 'audio_rename_window') and self.app.audio_rename_window:
                    win = self.app.audio_rename_window

            if win:
                # Próba ustawienia indeksu na wybraną linię
                if hasattr(win, 'current_index'):
                    win.current_index = start_index
                    # Odświeżenie widoku w oknie (metody typowe dla takich okien)
                    if hasattr(win, 'load_pair'):
                        win.load_pair()
                    elif hasattr(win, 'update_ui'):
                        win.update_ui()
                    elif hasattr(win, 'refresh'):
                        win.refresh()
                win.lift()
                win.focus_force()
            else:
                messagebox.showerror("Błąd", "Nie znaleziono klasy AudioRenameWindow.", parent=self)

        except Exception as e:
            print(f"Błąd otwierania okna dopasowania: {e}")
            messagebox.showerror("Błąd", f"Nie udało się otworzyć okna naprawy:\n{e}", parent=self)

    def delete_audio(self, ident, refresh_ui=True):
        """Usuwa pliki audio skojarzone z danym ID. Zwraca True jeśli coś usunięto."""
        ident_str = str(ident)
        deleted_any = False

        files_to_remove = [
            self.audio_dir / f"output1 ({ident_str}).wav",
            self.audio_dir / f"output1 ({ident_str}).mp3",
            self.audio_dir / "ready" / f"output1 ({ident_str}).ogg",
            self.audio_dir / "ready" / f"output1 ({ident_str}).mp3",
            self.audio_dir / "ready" / f"output1 ({ident_str}).wav"
        ]

        for f in files_to_remove:
            if f.exists():
                try:
                    os.remove(f)
                    deleted_any = True
                except Exception as e:
                    print(f"Nie udało się usunąć {f}: {e}")

        if deleted_any:
            for item in self.analysis_results:
                if item["id"] == ident:
                    item["path"] = None
                    item["duration"] = 0.0
                    item["cps"] = 0.0
                    item["raw_status"] = "USUNIĘTO"
                    item["ext"] = ""
                    item["is_error"] = True
                    break

            if ident_str in self.cache_data:
                del self.cache_data[ident_str]
                self._save_cache()

            if refresh_ui:
                self.refresh_list_view()

        return deleted_any

    # --- Audio helpers ---

    def get_audio_duration(self, file_path, ext):
        file_path = str(file_path)
        if ext == 'wav':
            try:
                with contextlib.closing(wave.open(file_path, 'r')) as f:
                    frames = f.getnframes()
                    rate = f.getframerate()
                    return (frames / float(rate)), None
            except Exception:
                pass
        if ext == 'mp3' and MUTAGEN_AVAILABLE:
            try:
                audio = MP3(file_path)
                return audio.info.length, None
            except Exception:
                pass
        if self.ffprobe_path:
            try:
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                cmd = [self.ffprobe_path, "-v", "error", "-show_entries", "format=duration", "-of",
                       "default=noprint_wrappers=1:nokey=1", file_path]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     startupinfo=startupinfo, timeout=5)
                if res.returncode != 0: return -1.0, res.stderr.strip()
                val = res.stdout.strip()
                return float(val) if val else -1.0, None
            except Exception as e:
                return -1.0, str(e)
        return -1.0, "Brak narzędzia"

    def play_audio(self, path):
        self.stop_audio()
        path = str(path)
        if self.ffplay_path:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            try:
                self.current_audio_process = subprocess.Popen([self.ffplay_path, "-nodisp", "-autoexit", path],
                                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                              startupinfo=startupinfo)
            except Exception:
                self._play_fallback(path)
        else:
            self._play_fallback(path)

    def _play_fallback(self, path):
        if os.name == 'nt':
            os.startfile(path)
        else:
            subprocess.call(['xdg-open', path])