import customtkinter as ctk
import os
import wave
import subprocess
import contextlib
import threading
import time
import shutil
import json
from pathlib import Path

# Próba importu mutagen dla MP3
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
        self.subtitles = subtitles  # To są już teksty TTS (processed_replace) przekazane ze studio.py

        self.running = False
        self.stop_event = threading.Event()
        self.analysis_results = []
        self.current_audio_process = None

        # Cache setup
        self.cache_file = None
        if self.app.loaded_path:
            # Tworzymy plik cache obok pliku napisów: np. "film.txt" -> "film.cps_cache.json"
            self.cache_file = self.app.loaded_path.with_suffix(".cps_cache.json")
        self.cache_data = {}

        # Sprawdzanie narzędzi
        self.ffplay_path = shutil.which("ffplay")
        self.ffprobe_path = shutil.which("ffprobe")

        self.avg_cps = 15.0
        self.error_details = {}

        self.title(f"Weryfikacja audio ({len(subtitles)} linii)")
        self.geometry("1200x800")

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
        self.top_frame.grid_columnconfigure(1, weight=1)

        # Lewa strona
        self.ctrl_panel = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.ctrl_panel.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        self.lbl_status = ctk.CTkLabel(self.ctrl_panel, text="Inicjalizacja...", font=("", 14, "bold"))
        self.lbl_status.pack(anchor="w")

        self.progress_bar = ctk.CTkProgressBar(self.ctrl_panel, width=300)
        self.progress_bar.pack(anchor="w", pady=5)
        self.progress_bar.set(0)

        self.btn_cancel = ctk.CTkButton(self.ctrl_panel, text="Zatrzymaj", fg_color="red",
                                        command=self.cancel_analysis, state="disabled", width=100)
        self.btn_cancel.pack(side="left", pady=5, padx=(0, 10))

        self.btn_show_errors = ctk.CTkButton(self.ctrl_panel, text="Szczegóły błędów (!)", fg_color="orange",
                                             text_color="black",
                                             command=self.show_error_details, state="disabled", width=140)
        self.btn_show_errors.pack(side="left", pady=5, padx=(0, 10))

        # Checkbox do wymuszenia odświeżenia cache
        self.var_force_refresh = ctk.BooleanVar(value=False)
        self.cb_force_refresh = ctk.CTkCheckBox(self.ctrl_panel, text="Wymuś pełną analizę (ignoruj cache)",
                                                variable=self.var_force_refresh)
        self.cb_force_refresh.pack(side="left", pady=5)

        # Prawa strona: Filtry
        self.filters_frame = ctk.CTkFrame(self.top_frame)
        self.filters_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        ctk.CTkLabel(self.filters_frame, text="Filtry i Tolerancja CPS", font=("", 12, "bold")).grid(row=0, column=0,
                                                                                                     columnspan=4,
                                                                                                     pady=(5, 0))

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

        self.var_ignore_short = ctk.BooleanVar(value=True)
        self.cb_ignore_short = ctk.CTkCheckBox(self.filters_frame, text="Ignoruj krótkie (<5 zn.)",
                                               variable=self.var_ignore_short, command=self.refresh_list_view)
        self.cb_ignore_short.grid(row=2, column=0, columnspan=2, pady=5, padx=10, sticky="w")

        self.var_show_only_errors = ctk.BooleanVar(value=True)
        self.sw_filter = ctk.CTkSwitch(self.filters_frame, text="Tylko problemy", variable=self.var_show_only_errors,
                                       command=self.refresh_list_view)
        self.sw_filter.grid(row=2, column=2, columnspan=2, pady=5, padx=10, sticky="e")

        # =====================================================================
        # 2. STATYSTYKI
        # =====================================================================
        self.stats_frame = ctk.CTkFrame(self)
        self.stats_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.lbl_stats = ctk.CTkLabel(self.stats_frame, text="Oczekiwanie...", font=("", 12))
        self.lbl_stats.pack(pady=5)

        # =====================================================================
        # 3. LISTA
        # =====================================================================
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

        headers = ["ID", "Tekst (fragment)", "Czas", "CPS", "Status", "Format", "Odsłuch"]
        self.scroll_frame.grid_columnconfigure(1, weight=1)

        for idx, h in enumerate(headers):
            ctk.CTkLabel(self.scroll_frame, text=h, font=("", 12, "bold")).grid(row=0, column=idx, padx=5, pady=5,
                                                                                sticky="w")

        if not self.ffprobe_path and not MUTAGEN_AVAILABLE:
            self.lbl_status.configure(text="Ostrzeżenie: Brak ffprobe! Analiza MP3 może nie działać.",
                                      text_color="orange")

        self.after(500, self.start_analysis)

    def on_close(self):
        if self.running:
            self.cancel_analysis()
        self.stop_audio()
        self.destroy()

    def stop_audio(self):
        if self.current_audio_process:
            if self.current_audio_process.poll() is None:
                self.current_audio_process.terminate()
            self.current_audio_process = None

    def cancel_analysis(self):
        if self.running:
            self.stop_event.set()
            self.lbl_status.configure(text="Zatrzymywanie...")
            self.btn_cancel.configure(state="disabled")

    def show_error_details(self):
        if not self.error_details: return
        win = ctk.CTkToplevel(self)
        win.title("Szczegóły błędów")
        win.geometry("600x400")
        txt = ctk.CTkTextbox(win)
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        msg = "Przykładowe błędy (pierwsze 20):\n\n"
        for i, (ident, err) in enumerate(self.error_details.items()):
            if i > 20: break
            msg += f"ID {ident}: {err}\n"
        txt.insert("1.0", msg)
        txt.configure(state="disabled")

    # --- Cache Logic ---
    def _load_cache(self):
        if self.cache_file and self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache_data = json.load(f)
                print(f"Załadowano cache: {len(self.cache_data)} wpisów.")
            except Exception as e:
                print(f"Błąd ładowania cache: {e}")
                self.cache_data = {}

    def _save_cache(self):
        if self.cache_file:
            try:
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.cache_data, f, ensure_ascii=False)
                print("Zapisano cache.")
            except Exception as e:
                print(f"Błąd zapisu cache: {e}")

    def start_analysis(self):
        self.running = True
        self.stop_event.clear()
        self.analysis_results = []
        self.error_details = {}
        self.btn_cancel.configure(state="normal")
        self.btn_show_errors.configure(state="disabled")
        self.lbl_status.configure(text="Ładowanie cache i skanowanie...", text_color=["black", "white"])
        self.progress_bar.set(0)

        # Reset UI
        for widget in self.scroll_frame.winfo_children():
            if int(widget.grid_info()["row"]) > 0:
                widget.destroy()

        thread = threading.Thread(target=self._analysis_worker, daemon=True)
        thread.start()

    def get_audio_duration(self, file_path, ext):
        """Pobiera długość audio. Zwraca (duration, error_message)."""
        file_path = str(file_path)

        # 1. MP3 - Mutagen
        if ext == 'mp3' and MUTAGEN_AVAILABLE:
            try:
                audio = MP3(file_path)
                return audio.info.length, None
            except Exception:
                pass

        # 2. Fallback: FFprobe
        if self.ffprobe_path:
            try:
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                cmd = [
                    self.ffprobe_path, "-v", "error", "-show_entries",
                    "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path
                ]

                result = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, startupinfo=startupinfo, timeout=5
                )

                if result.returncode != 0:
                    return -1.0, f"FFprobe: {result.stderr.strip()}"

                val = result.stdout.strip()
                if not val:
                    return -1.0, "FFprobe empty result"
                return float(val), None
            except Exception as e:
                return -1.0, f"FFprobe exc: {str(e)}"

        return -1.0, "Brak narzędzia (ffprobe)"

    def _analysis_worker(self):
        # 1. Ładowanie cache
        force_refresh = self.var_force_refresh.get()
        if not force_refresh:
            self._load_cache()
        else:
            self.cache_data = {}  # Wymuszone czyszczenie w pamięci

        total_lines = len(self.subtitles)
        total_chars_global = 0
        total_duration_global = 0
        valid_files_count = 0

        processed_count = 0
        last_update_time = time.time()

        new_cache_data = {}  # Budujemy nowy cache (sprzątanie starych wpisów)

        for i, text in enumerate(self.subtitles):
            if self.stop_event.is_set():
                break

            ident = str(i + 1)  # Cache klucz to ID jako string
            text_clean = text.strip()

            if not text_clean:
                processed_count += 1
                continue

            # Szukanie pliku
            audio_file = None
            found_ext = ""

            paths_to_check = [
                (self.audio_dir / f"output1 ({ident}).wav", "wav"),
                (self.audio_dir / f"output1 ({ident}).mp3", "mp3"),
                (self.audio_dir / "ready" / f"output1 ({ident}).ogg", "ogg"),
                (self.audio_dir / "ready" / f"output1 ({ident}).mp3", "mp3")
            ]

            for p, ext in paths_to_check:
                if p.exists():
                    audio_file = p
                    found_ext = ext
                    break

            duration = 0.0
            cps = 0.0
            raw_status = "MISSING"
            error_msg = None

            # --- LOGIKA CACHE ---
            cache_hit = False
            # Sprawdzamy czy mamy wpis w cache, czy tekst jest taki sam i czy plik nadal istnieje
            if not force_refresh and ident in self.cache_data:
                entry = self.cache_data[ident]
                # Porównujemy tekst z cache z obecnym tekstem TTS
                # Sprawdzamy też czy ścieżka z cache istnieje (szybki check)
                if entry.get("text") == text_clean and entry.get("path") and os.path.exists(entry["path"]):
                    # Cache HIT
                    duration = entry["duration"]
                    error_msg = entry.get("error")
                    audio_file = Path(entry["path"])
                    found_ext = entry.get("ext", "")
                    cache_hit = True

            # Jeśli nie ma w cache (lub wymuszono), analizujemy plik
            if not cache_hit and audio_file:
                duration, error_msg = self.get_audio_duration(audio_file, found_ext)

            # Interpretacja wyników
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
                    total_chars_global += char_count
                    total_duration_global += duration
                    valid_files_count += 1

                # Aktualizacja/Dodanie do nowego cache
                new_cache_data[ident] = {
                    "text": text_clean,
                    "duration": duration,
                    "path": str(audio_file),
                    "ext": found_ext,
                    "error": error_msg
                }

            self.analysis_results.append({
                "id": int(ident),
                "text": text,
                "duration": duration,
                "cps": cps,
                "raw_status": raw_status,
                "path": audio_file,
                "ext": found_ext
            })
            processed_count += 1

            # Update UI
            current_time = time.time()
            if (processed_count % 50 == 0) or (current_time - last_update_time > 0.1):
                progress = processed_count / total_lines
                self.app.after(0, lambda p=progress, c=processed_count: self._update_progress_ui(p, c, total_lines))
                last_update_time = current_time

        # Średnia
        if total_duration_global > 0:
            self.avg_cps = total_chars_global / total_duration_global
        else:
            self.avg_cps = 15.0

        # Zapisz cache (podmieniamy stary na nowy, czyszcząc nieistniejące linie)
        self.cache_data = new_cache_data
        self._save_cache()

        self.app.after(0, lambda: self._finalize_ui(processed_count, valid_files_count))

    def _update_progress_ui(self, progress, current, total):
        self.progress_bar.set(progress)
        self.lbl_status.configure(text=f"Analiza: {current}/{total}...")

    def _finalize_ui(self, total_processed, valid_count):
        self.running = False
        self.btn_cancel.configure(state="disabled")
        self.progress_bar.set(1.0)

        if self.error_details:
            self.btn_show_errors.configure(state="normal")
            self.lbl_status.configure(text="Zakończono z błędami!", text_color="red")
        else:
            self.lbl_status.configure(text="Gotowe.")

        self.refresh_list_view()

    def on_slider_change(self, value):
        self.lbl_min_cps.configure(text=f"Min: {self.slider_min_cps.get():.1f}")
        self.lbl_max_cps.configure(text=f"Max: {self.slider_max_cps.get():.1f}")
        self.refresh_list_view()

    def refresh_list_view(self, *args):
        # Clear
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

            if is_error:
                suspicious_count += 1

            if show_errors_only:
                if is_error:
                    filtered_items.append(item)
            else:
                filtered_items.append(item)

        # Stats info
        err_count = len(self.error_details)
        err_msg = f" (Błędy odczytu: {err_count})" if err_count > 0 else ""

        stats_txt = (f"Średnie CPS: {self.avg_cps:.1f}. "
                     f"Znaleziono {suspicious_count} odchyleń{err_msg}.")
        self.lbl_stats.configure(text=stats_txt)

        # Render list (limit 200 dla wydajności)
        LIMIT = 50
        row = 1

        if not filtered_items:
            ctk.CTkLabel(self.scroll_frame, text="Brak wyników do wyświetlenia.").grid(row=row, column=1)
            return

        for item in filtered_items[:LIMIT]:
            color = "white"
            st = item["display_status"]

            if "ZA SZYBKO" in st or "ZA WOLNO" in st:
                color = "orange"
            elif "ERROR" in st or "MISSING" in st:
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

            if item["path"]:
                btn = ctk.CTkButton(self.scroll_frame, text="▶", width=30, height=20,
                                    command=lambda p=item["path"]: self.play_audio(p))
                btn.grid(row=row, column=6, padx=5, pady=2)

            row += 1

        if len(filtered_items) > LIMIT:
            ctk.CTkLabel(self.scroll_frame, text=f"... {len(filtered_items) - LIMIT} więcej ...").grid(row=row,
                                                                                                       column=1)

    def play_audio(self, path):
        self.stop_audio()
        path = str(path)

        if self.ffplay_path:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            try:
                self.current_audio_process = subprocess.Popen(
                    [self.ffplay_path, "-nodisp", "-autoexit", path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    startupinfo=startupinfo
                )
            except Exception:
                self._play_fallback(path)
        else:
            self._play_fallback(path)

    def _play_fallback(self, path):
        if os.name == 'nt':
            os.startfile(path)
        else:
            subprocess.call(['xdg-open', path])