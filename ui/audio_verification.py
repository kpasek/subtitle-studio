import customtkinter as ctk
import os
import subprocess
import threading
import time
import shutil
import json
from pathlib import Path
from tkinter import ttk, messagebox

# Próba importu okna do naprawy nazw plików (AudioRenameWindow)
try:
    from audio.audio_renamer import AudioRenameWindow
except ImportError:
    AudioRenameWindow = None

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
        self.subtitles = subtitles

        # --- Stan Aplikacji ---
        self.running = False
        self.stop_event = threading.Event()

        # Dane
        self.analysis_results = []
        self.filtered_items = []
        self.cache_data = {}

        self.current_audio_process = None
        self.processed_indices = set()

        # Cache setup
        self.cache_file = None
        if self.app.loaded_path:
            self.cache_file = self.app.loaded_path.with_suffix(".cps_cache.json")

        # Sprawdzanie narzędzi
        self.ffplay_path = shutil.which("ffplay")
        self.ffprobe_path = shutil.which("ffprobe")

        self.avg_cps = 15.0
        self.error_details = {}

        # --- Ustawienia Okna ---
        self.title(f"Weryfikacja audio ({len(subtitles)} linii)")
        self.geometry("1280x850")

        # FIX: Okno pojawia się na wierzchu, ale nie jest "przyspawane" (nie blokuje dialogów)
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._setup_treeview_style()

        # --- UKŁAD GRID ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # Tabela rozciąga się w pionie

        # =====================================================================
        # 1. GÓRNY PANEL (Sterowanie)
        # =====================================================================
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.top_frame.grid_columnconfigure(2, weight=1)

        # -- Sekcja A: Przyciski Start/Stop --
        self.ctrl_frame = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.ctrl_frame.grid(row=0, column=0, sticky="ns", padx=5, pady=5)

        self.btn_start = ctk.CTkButton(self.ctrl_frame, text="Start", command=self.toggle_analysis,
                                       fg_color="green", width=120)
        self.btn_start.pack(side="left", padx=5)

        self.btn_stop = ctk.CTkButton(self.ctrl_frame, text="Zatrzymaj", command=self.stop_analysis,
                                      fg_color="red", state="disabled", width=100)
        self.btn_stop.pack(side="left", padx=5)

        # -- Sekcja B: Opcje Skanowania --
        self.opts_frame = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.opts_frame.grid(row=0, column=1, sticky="ns", padx=20, pady=5)

        self.var_stop_on_error = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.opts_frame, text="Zatrzymaj na błędzie",
                        variable=self.var_stop_on_error).pack(anchor="w")

        self.var_auto_sync = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.opts_frame, text="Auto-kalibracja (po 20 plikach)", variable=self.var_auto_sync).pack(
            anchor="w")

        self.var_force_refresh = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.opts_frame, text="Wymuś pełną analizę (ignoruj cache)",
                        variable=self.var_force_refresh).pack(anchor="w")

        # -- Sekcja C: Status i Pasek Postępu --
        self.status_frame = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.status_frame.grid(row=0, column=2, sticky="nsew", padx=5)

        self.lbl_status = ctk.CTkLabel(self.status_frame, text="Gotowy do startu.", font=("", 14, "bold"))
        self.lbl_status.pack(anchor="e", padx=10)

        self.progress_bar = ctk.CTkProgressBar(self.status_frame)
        self.progress_bar.pack(fill="x", pady=5, padx=10)
        self.progress_bar.set(0)

        # =====================================================================
        # 2. PANEL FILTRÓW
        # =====================================================================
        self.filter_frame = ctk.CTkFrame(self)
        self.filter_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.filter_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.filter_frame, text="Filtry Wyświetlania:", font=("", 12, "bold")).pack(side="left", padx=10)

        self.slider_cont = ctk.CTkFrame(self.filter_frame, fg_color="transparent")
        self.slider_cont.pack(side="left", fill="x", expand=True, padx=10)

        self.lbl_min_cps = ctk.CTkLabel(self.slider_cont, text="Min CPS: 3.0", width=80)
        self.lbl_min_cps.pack(side="left")
        self.slider_min_cps = ctk.CTkSlider(self.slider_cont, from_=1.0, to=20.0, number_of_steps=190,
                                            command=self.on_slider_change)
        self.slider_min_cps.set(3.0)
        self.slider_min_cps.pack(side="left", fill="x", expand=True, padx=5)

        self.lbl_max_cps = ctk.CTkLabel(self.slider_cont, text="Max CPS: 25.0", width=80)
        self.lbl_max_cps.pack(side="left")
        self.slider_max_cps = ctk.CTkSlider(self.slider_cont, from_=10.0, to=50.0, number_of_steps=400,
                                            command=self.on_slider_change)
        self.slider_max_cps.set(25.0)
        self.slider_max_cps.pack(side="left", fill="x", expand=True, padx=5)

        self.var_ignore_short = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.filter_frame, text="Ignoruj krótkie (<5 zn.)", variable=self.var_ignore_short,
                        command=self.refresh_list_view).pack(side="left", padx=10)

        self.var_show_only_errors = ctk.BooleanVar(value=True)
        self.sw_filter = ctk.CTkSwitch(self.filter_frame, text="Tylko problemy", variable=self.var_show_only_errors,
                                       command=self.refresh_list_view)
        self.sw_filter.pack(side="right", padx=10)

        # =====================================================================
        # 3. TABELA (Treeview)
        # =====================================================================
        self.tree_frame = ctk.CTkFrame(self)
        self.tree_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 5))
        self.tree_frame.grid_columnconfigure(0, weight=1)
        self.tree_frame.grid_rowconfigure(0, weight=1)

        columns = ("id", "text", "duration", "cps", "status", "format")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("id", text="ID")
        self.tree.heading("text", text="Tekst (fragment)")
        self.tree.heading("duration", text="Czas [s]")
        self.tree.heading("cps", text="CPS")
        self.tree.heading("status", text="Status")
        self.tree.heading("format", text="Format")

        self.tree.column("id", width=50, anchor="center")
        self.tree.column("text", width=600, anchor="w")
        self.tree.column("duration", width=80, anchor="center")
        self.tree.column("cps", width=60, anchor="center")
        self.tree.column("status", width=200, anchor="center")
        self.tree.column("format", width=60, anchor="center")

        self.scrollbar = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.scrollbar.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        self.tree.tag_configure("ok", foreground="white")
        self.tree.tag_configure("warn", foreground="orange")
        self.tree.tag_configure("error", foreground="#ff5555")
        self.tree.tag_configure("short", foreground="gray")

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        # =====================================================================
        # 4. PANEL AKCJI
        # =====================================================================
        self.actions_frame = ctk.CTkFrame(self)
        self.actions_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=10)

        self.lbl_stats = ctk.CTkLabel(self.actions_frame, text="Oczekiwanie na start...")
        self.lbl_stats.pack(side="left", padx=10)

        self.btn_fix_sync = ctk.CTkButton(self.actions_frame, text="🛠 Napraw (Przesunięcie)",
                                          command=self.open_renamer, width=160, fg_color="#726a95", state="disabled")
        self.btn_fix_sync.pack(side="right", padx=5)

        self.btn_del_single = ctk.CTkButton(self.actions_frame, text="🗑 Usuń plik",
                                            command=self.delete_current_audio, width=100, fg_color="#a83232",
                                            state="disabled")
        self.btn_del_single.pack(side="right", padx=5)

        self.btn_play = ctk.CTkButton(self.actions_frame, text="▶ Odtwórz",
                                      command=self.play_selected, width=100, state="disabled")
        self.btn_play.pack(side="right", padx=5)

        # Akcje globalne
        self.actions_global = ctk.CTkFrame(self)
        self.actions_global.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))

        self.btn_del_all_errors = ctk.CTkButton(self.actions_global, text="🗑 Usuń WSZYSTKIE błędne pliki",
                                                command=self.delete_all_bad_audio, fg_color="darkred", width=200,
                                                state="disabled")
        self.btn_del_all_errors.pack(side="right", padx=10)

        self.btn_open_folder = ctk.CTkButton(self.actions_global, text="📂 Otwórz folder",
                                             command=self.open_folder_selected, width=120, fg_color="#444")
        self.btn_open_folder.pack(side="left", padx=10)

        if not self.ffprobe_path and not MUTAGEN_AVAILABLE:
            self.lbl_status.configure(text="Ostrzeżenie: Brak ffprobe! Analiza może być niepełna.", text_color="orange")

        self._load_cache()

    def _setup_treeview_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        bg = "#2b2b2b"
        fg = "white"
        header_bg = "#1f1f1f"

        style.configure("Treeview", background=bg, foreground=fg, fieldbackground=bg, borderwidth=0, rowheight=25)
        style.configure("Treeview.Heading", background=header_bg, foreground=fg, relief="flat")
        style.map("Treeview", background=[("selected", "#1f538d")], foreground=[("selected", "white")])
        style.map("Treeview.Heading", background=[("active", "#333333")])

    # --- Logika Sterowania ---

    def toggle_analysis(self):
        if not self.running:
            self.start_analysis()

    def start_analysis(self):
        self.running = True
        self.stop_event.clear()
        self.btn_start.configure(state="disabled", text="Przetwarzanie...")
        self.btn_stop.configure(state="normal")
        self.btn_del_all_errors.configure(state="disabled")

        force_refresh = self.var_force_refresh.get()
        stop_on_error = self.var_stop_on_error.get()
        auto_sync = self.var_auto_sync.get()

        if force_refresh:
            for item in self.tree.get_children(): self.tree.delete(item)
            self.analysis_results = []
            self.processed_indices.clear()

        thread = threading.Thread(
            target=self._analysis_worker,
            args=(force_refresh, stop_on_error, auto_sync),
            daemon=True
        )
        thread.start()

    def stop_analysis(self):
        self.running = False
        self.stop_event.set()
        self.lbl_status.configure(text="Zatrzymywanie...", text_color="orange")
        self.btn_stop.configure(state="disabled")
        self.btn_start.configure(state="normal", text="Wznów")

    def on_close(self):
        self.stop_analysis()
        self.stop_audio()
        self.destroy()

    # --- Worker Analizy ---

    def _analysis_worker(self, force_refresh, stop_on_error, auto_sync):
        if force_refresh:
            self.cache_data = {}

        total_lines = len(self.subtitles)
        processed_count = 0
        valid_files_cps_sum = 0
        valid_files_count = 0
        stopped_on_error_flag = False

        if not self.analysis_results:
            for i, text in enumerate(self.subtitles):
                self.analysis_results.append({
                    "id": i + 1,
                    "text": text,
                    "duration": 0.0,
                    "cps": 0.0,
                    "raw_status": "PENDING",
                    "path": None,
                    "ext": ""
                })

        new_cache_data = self.cache_data.copy()

        for i, text in enumerate(self.subtitles):
            if self.stop_event.is_set():
                break

            ident_str = str(i + 1)

            if (i in self.processed_indices) and not force_refresh:
                processed_count += 1
                continue

            text_clean = text.strip()
            if not text_clean:
                processed_count += 1
                continue

            # Szukanie plików
            audio_file = None
            found_ext = ""
            paths_to_check = [
                (self.audio_dir / f"output1 ({ident_str}).wav", "wav"),
                (self.audio_dir / f"output1 ({ident_str}).mp3", "mp3"),
                (self.audio_dir / "ready" / f"output1 ({ident_str}).ogg", "ogg"),
                (self.audio_dir / "ready" / f"output1 ({ident_str}).mp3", "mp3")
            ]

            for p, ext in paths_to_check:
                if p.exists():
                    audio_file = p
                    found_ext = ext
                    break

            duration = 0.0
            error_msg = None
            cache_hit = False

            if not force_refresh and ident_str in self.cache_data:
                entry = self.cache_data[ident_str]
                if entry.get("text") == text_clean and entry.get("path") and os.path.exists(entry["path"]):
                    duration = entry["duration"]
                    error_msg = entry.get("error")
                    audio_file = Path(entry["path"])
                    found_ext = entry.get("ext", "")
                    cache_hit = True

            if not cache_hit and audio_file:
                duration, error_msg = self.get_audio_duration(audio_file, found_ext)
                if duration > 0:
                    new_cache_data[ident_str] = {
                        "text": text_clean, "duration": duration,
                        "path": str(audio_file), "ext": found_ext, "error": None
                    }

            raw_status = "OK"
            cps = 0.0

            if not audio_file:
                raw_status = "MISSING"
            elif duration < 0:
                raw_status = "ERROR"
                self.error_details[ident_str] = f"Błąd: {error_msg}"
            elif duration == 0:
                raw_status = "EMPTY"
            else:
                cps = len(text_clean) / duration
                valid_files_cps_sum += cps
                valid_files_count += 1

            self.analysis_results[i].update({
                "duration": duration,
                "cps": cps,
                "raw_status": raw_status,
                "path": audio_file,
                "ext": found_ext
            })

            self.processed_indices.add(i)
            processed_count += 1

            if auto_sync and valid_files_count == 20:
                avg = valid_files_cps_sum / 20
                self.app.after(0, lambda a=avg: self._auto_adjust_thresholds(a))

            # Zatrzymanie na błędzi
            if stop_on_error and raw_status in ["ERROR", "EMPTY"]:
                msg_txt = f"Wykryto problem z plikiem ID {ident_str}!\n{error_msg or 'Pusty plik (0s)'}"
                self.app.after(0, lambda m=msg_txt: messagebox.showerror("Błąd Audio", m))
                stopped_on_error_flag = True
                break

            if processed_count % 10 == 0:
                self.app.after(0, lambda p=processed_count / total_lines: self.progress_bar.set(p))
                self.app.after(0,
                               lambda c=processed_count: self.lbl_status.configure(text=f"Analiza: {c}/{total_lines}"))
                if processed_count % 50 == 0:
                    self.app.after(0, self.refresh_list_view)

        self.cache_data = new_cache_data
        self._save_cache()
        self.app.after(0, lambda: self._finalize_ui(processed_count, stopped_on_error_flag))

    def _finalize_ui(self, count, stopped_on_error=False):
        self.running = False
        self.btn_start.configure(state="normal", text="Start")
        self.btn_stop.configure(state="disabled")

        if not stopped_on_error:
            self.progress_bar.set(1.0)
            self.lbl_status.configure(text=f"Zakończono. Przeanalizowano: {count}")
        else:
            self.lbl_status.configure(text=f"Zatrzymano na błędzie. Przeanalizowano: {count}", text_color="red")

        self.refresh_list_view()
        self.btn_del_all_errors.configure(state="normal")

    def _auto_adjust_thresholds(self, avg_cps):
        new_min = max(1.0, avg_cps - 5.0)
        new_max = avg_cps + 5.0
        self.slider_min_cps.set(new_min)
        self.slider_max_cps.set(new_max)
        self.on_slider_change(None)

    def get_audio_duration(self, file_path, ext):
        file_path = str(file_path)
        if ext == 'mp3' and MUTAGEN_AVAILABLE:
            try:
                return MP3(file_path).info.length, None
            except:
                pass

        if self.ffprobe_path:
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                cmd = [self.ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                       "-of", "default=noprint_wrappers=1:nokey=1", file_path]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     startupinfo=startupinfo)
                if res.returncode == 0 and res.stdout.strip():
                    return float(res.stdout.strip()), None
                return -1.0, res.stderr
            except Exception as e:
                return -1.0, str(e)
        return -1.0, "Brak ffprobe"

    # --- Lista i Filtrowanie ---

    def refresh_list_view(self, *args):
        for item in self.tree.get_children():
            self.tree.delete(item)

        min_cps = self.slider_min_cps.get()
        max_cps = self.slider_max_cps.get()
        ignore_short = self.var_ignore_short.get()
        show_errors = self.var_show_only_errors.get()

        self.filtered_items = []
        suspicious_count = 0

        for item in self.analysis_results:
            if item["raw_status"] == "PENDING": continue

            display_status = "OK"
            tag = "ok"
            is_problem = False

            if item["raw_status"] != "OK":
                display_status = item["raw_status"]
                is_problem = True
                tag = "error"
            else:
                cps = item["cps"]
                txt_len = len(item["text"])

                if ignore_short and txt_len < 5:
                    display_status = "SHORT"
                    tag = "short"
                else:
                    if cps < min_cps:
                        display_status = f"ZA WOLNO (<{min_cps:.1f})"
                        is_problem = True
                        tag = "warn"
                    elif cps > max_cps:
                        display_status = f"ZA SZYBKO (>{max_cps:.1f})"
                        is_problem = True
                        tag = "warn"

            item["display_status"] = display_status

            if is_problem: suspicious_count += 1

            if show_errors and not is_problem:
                continue

            self.filtered_items.append(item)

            val_txt = (item["text"][:80] + "...") if len(item["text"]) > 80 else item["text"]
            val_dur = f"{item['duration']:.2f}" if item["duration"] > 0 else "-"
            val_cps = f"{item['cps']:.1f}" if item["duration"] > 0 else "-"
            val_fmt = item["ext"].upper()

            self.tree.insert("", "end", values=(item["id"], val_txt, val_dur, val_cps, display_status, val_fmt),
                             tags=(tag,))

        self.lbl_stats.configure(text=f"Wyświetlono: {len(self.filtered_items)} | Problemy: {suspicious_count}")

    # --- Akcje ---

    def on_tree_select(self, event):
        item = self.get_selected_item()

        if item:
            self.btn_fix_sync.configure(state="normal")
        else:
            self.btn_fix_sync.configure(state="disabled")

        if item and item["path"]:
            self.btn_play.configure(state="normal")
            self.btn_del_single.configure(state="normal")
        else:
            self.btn_play.configure(state="disabled")
            self.btn_del_single.configure(state="disabled")

    def on_tree_double_click(self, event):
        self.play_selected()

    def get_selected_item(self):
        sel = self.tree.selection()
        if not sel: return None
        item_id = self.tree.item(sel[0])['values'][0]
        return next((x for x in self.analysis_results if x["id"] == int(item_id)), None)

    def play_selected(self):
        item = self.get_selected_item()
        if item and item["path"]: self.play_audio(item["path"])

    def open_renamer(self):
        if AudioRenameWindow is None:
            messagebox.showerror("Błąd", "Moduł AudioRenameWindow nie jest dostępny.")
            return

        item = self.get_selected_item()
        if not item: return

        self.stop_audio()
        win = AudioRenameWindow(self.app, self.audio_dir, initial_target=item["id"])
        self.wait_window(win)
        self.refresh_list_view()

    def open_folder_selected(self):
        item = self.get_selected_item()
        p = item["path"] if item and item["path"] else self.audio_dir
        path = Path(p).parent if p else self.audio_dir
        if os.name == 'nt':
            os.startfile(path)
        else:
            subprocess.call(['xdg-open', path])

    def delete_current_audio(self):
        item = self.get_selected_item()
        if not item or not item["path"]: return

        self.stop_audio()

        if messagebox.askyesno("Usuń", f"Usunąć plik ID {item['id']}?"):
            try:
                os.remove(item["path"])
                idx = item["id"] - 1
                self.analysis_results[idx]["raw_status"] = "MISSING"
                self.analysis_results[idx]["path"] = None
                self.analysis_results[idx]["duration"] = 0
                self.processed_indices.discard(idx)

                if str(item["id"]) in self.cache_data:
                    del self.cache_data[str(item["id"])]

                self.refresh_list_view()
                messagebox.showinfo("OK", "Plik usunięty.")
            except Exception as e:
                messagebox.showerror("Błąd", str(e))

    def delete_all_bad_audio(self):
        # Usuwamy pliki widoczne jako błędne na podstawie filtered_items
        to_del = []
        for item in self.filtered_items:
            # Musi mieć ścieżkę (istnieć) i być błędem
            if not item.get("path"):
                continue

            status = item.get("display_status", "OK")
            # Akceptujemy statusy wskazujące na błąd/ostrzeżenie
            if status not in ["OK", "SHORT", "MISSING", "PENDING"]:
                to_del.append(item)

        if not to_del:
            messagebox.showinfo("Info", "Brak błędnych plików do usunięcia (w aktualnym widoku).")
            return

        self.stop_audio()

        if messagebox.askyesno("Potwierdź", f"Usunąć {len(to_del)} widocznych błędnych plików?"):
            count = 0
            errors = []

            for item in to_del:
                path_to_remove = Path(item["path"])
                try:
                    if path_to_remove.exists():
                        os.remove(path_to_remove)

                    # Aktualizacja stanu
                    idx = item["id"] - 1
                    self.analysis_results[idx]["raw_status"] = "MISSING"
                    self.analysis_results[idx]["path"] = None
                    self.analysis_results[idx]["duration"] = 0
                    self.analysis_results[idx]["display_status"] = "MISSING"

                    if str(item["id"]) in self.cache_data:
                        del self.cache_data[str(item["id"])]

                    count += 1
                except Exception as e:
                    errors.append(f"ID {item['id']}: {str(e)}")

            self.refresh_list_view()

            if errors:
                msg = f"Usunięto {count} plików.\nBłędy:\n" + "\n".join(errors[:10])
                if len(errors) > 10: msg += "\n..."
                messagebox.showwarning("Wynik", msg)
            else:
                messagebox.showinfo("Zakończono", f"Pomyślnie usunięto {count} plików.")

    def play_audio(self, path):
        self.stop_audio()
        path = str(path)
        if self.ffplay_path:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.current_audio_process = subprocess.Popen(
                [self.ffplay_path, "-nodisp", "-autoexit", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo
            )
        else:
            if os.name == 'nt':
                os.startfile(path)
            else:
                subprocess.call(['xdg-open', path])

    def stop_audio(self):
        if self.current_audio_process:
            if self.current_audio_process.poll() is None:
                self.current_audio_process.terminate()
            self.current_audio_process = None

    def _load_cache(self):
        if self.cache_file and self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache_data = json.load(f)
            except:
                self.cache_data = {}

    def _save_cache(self):
        if self.cache_file:
            try:
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.cache_data, f, ensure_ascii=False)
            except:
                pass

    def on_slider_change(self, _):
        self.lbl_min_cps.configure(text=f"Min: {self.slider_min_cps.get():.1f}")
        self.lbl_max_cps.configure(text=f"Max: {self.slider_max_cps.get():.1f}")
        self.refresh_list_view()