import multiprocessing
import os
import shutil
import json
import subprocess
import threading
import webbrowser
import requests
import re
import ctypes
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import queue
from datetime import datetime

from app.project import ProjectManager # Nowa klasa
from ui.dialogs import CommitDialog, TTSGenerationDialog, ConversionDialog

# Importy z aplikacji
from app.state import ProjectStateManager
from app.text_processing import apply_remove_patterns, apply_replace_patterns
from app.ui_windows import PatternWindow, AboutWindow
from app.utils import is_installed
from app.settings import SettingsWindow

# Audio / Generators
from audio.generation_manager import GenerationManager, GenerationJob, ConversionJob
from audio.pattern_editor import PatternEditorWindow
from audio.generation_queue import GenerationQueueWindow

# Optional Packaging
try:
    from packaging import version

    PACKAGING_AVAILABLE = True
except ImportError:
    PACKAGING_AVAILABLE = False

# --- WINDOWS DPI FIX ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass
# -----------------------

APP_TITLE = "Subtitle Studio 2.1 Refactored"
APP_VERSION = "2.1.2"
APP_CONFIG_FILE = Path.cwd() / ".subtitle_studio_config.json"

VIEW_MODE_TTS = "TTS (Podmiany)"
VIEW_MODE_CLEAN = "Czyste (Game Reader)"


class SubtitleStudioApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.title(APP_TITLE)
        self.geometry("1600x900")


        # Managers
        self.project = ProjectManager()
        self.gen_manager = GenerationManager.get_instance()

        # UI State Variables
        self.view_mode = tk.StringVar(value=VIEW_MODE_TTS)
        self.search_text = tk.StringVar()

        self.global_config = {}
        self.queue = queue.Queue()
        self.latest_version_info = None
        self.update_btn = None

        # Setup
        self._load_global_config()
        self._apply_theme()
        self._create_menu()
        self._create_layout()
        self._bind_shortcuts()

        # Async tasks
        self.check_queue_loop()
        threading.Thread(target=self._check_for_updates, daemon=True).start()

        # Load last project
        last_proj = self.global_config.get("last_project")
        if last_proj and os.path.exists(last_proj):
            try:
                self.open_project(last_proj)
            except:
                pass

    # --- UI Construction ---

    def _create_menu(self):
        menubar = tk.Menu(self)

        # --- Plik ---
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Nowy projekt (Ctrl+N)", command=self.new_project)
        file_menu.add_command(label="Otwórz projekt (.json)", command=self.open_project)

        recent_menu = tk.Menu(file_menu, tearoff=0)
        recent = self.global_config.get("recent_projects", [])
        if not recent:
            recent_menu.add_command(label="(Brak)", state="disabled")
        else:
            for path in recent:
                recent_menu.add_command(label=path, command=lambda p=path: self.open_project(p))
        file_menu.add_cascade(label="Ostatnie projekty", menu=recent_menu)

        file_menu.add_command(label="Zapisz projekt (Ctrl+S)", command=self.save_project)
        file_menu.add_separator()
        file_menu.add_command(label="Ustawienia Globalne", command=self.open_global_settings)
        file_menu.add_command(label="Ustawienia Projektu", command=self.open_project_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Wyjście", command=self.on_close)
        menubar.add_cascade(label="Plik", menu=file_menu)

        # --- Audio ---
        audio_menu = tk.Menu(menubar, tearoff=0)
        audio_menu.add_command(label="Wybierz katalog audio", command=self.choose_audio_dir)
        audio_menu.add_separator()
        audio_menu.add_command(label="Generuj wszystko TTS (Ctrl+Shift+G)", command=self.generate_audio_tts)
        audio_menu.add_command(label="Konwertuj audio (WAV->OGG)", command=self.generate_audio_convert)
        audio_menu.add_separator()
        audio_menu.add_command(label="Generuj aktualną linię (Ctrl+G)", command=self.generate_current_line)
        audio_menu.add_command(label="Odtwórz aktualną linię (Ctrl+Spacja)", command=self.play_current_line_audio)
        menubar.add_cascade(label="Audio", menu=audio_menu)

        # --- Eksport ---
        export_menu = tk.Menu(menubar, tearoff=0)
        export_menu.add_command(label="Eksport dla Game Reader", command=self.export_game_reader)
        export_menu.add_command(label="Eksport dla Lektor", command=self.export_lektor)
        export_menu.add_separator()
        export_menu.add_command(label="Eksport wzorców usuwających (CSV)",
                                command=lambda: self.export_patterns('remove'))
        export_menu.add_command(label="Eksport wzorców podmieniających (CSV)",
                                command=lambda: self.export_patterns('replace'))
        menubar.add_cascade(label="Eksport", menu=export_menu)

        # --- Pomoc ---
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="O programie", command=self.show_about)
        menubar.add_cascade(label="Pomoc", menu=help_menu)

        self.config(menu=menubar)

    def _create_layout(self):
        container = ctk.CTkFrame(self)
        container.pack(fill="both", expand=True, padx=5, pady=5)

        self._create_toolbar(container)

        paned = tk.PanedWindow(container, orient=tk.HORIZONTAL, sashwidth=6, bg="#2b2b2b")
        paned.pack(fill="both", expand=True, padx=5, pady=5)

        # Preview
        frame_left = ctk.CTkFrame(paned)
        paned.add(frame_left)
        ctk.CTkLabel(frame_left, text="PODGLĄD (ReadOnly)", font=("Arial", 12, "bold")).pack(pady=2)
        self.txt_preview = ctk.CTkTextbox(frame_left, state="disabled")
        self.txt_preview.pack(fill="both", expand=True, padx=2, pady=2)

        # Editor
        frame_right = ctk.CTkFrame(paned)
        paned.add(frame_right)
        self.lbl_editor = ctk.CTkLabel(frame_right, text="EDYTORY (Robocza)", font=("Arial", 12, "bold"))
        self.lbl_editor.pack(pady=2)
        self.txt_editor = ctk.CTkTextbox(frame_right)
        self.txt_editor.pack(fill="both", expand=True, padx=2, pady=2)

        self.lbl_status = ctk.CTkLabel(self, text="Gotowy", anchor="w")
        self.lbl_status.pack(side="bottom", fill="x", padx=10)

    def _create_toolbar(self, parent):
        toolbar = ctk.CTkFrame(parent, height=40)
        toolbar.pack(fill="x", side="top", padx=5, pady=5)

        # Lewa strona
        frame_left = ctk.CTkFrame(toolbar, fg_color="transparent")
        frame_left.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(frame_left, text="Wzorce:").pack(side="left", padx=5)
        ctk.CTkButton(frame_left, text="Wycinające", width=80,
                      command=lambda: self.open_patterns('remove')).pack(side="left", padx=2)
        ctk.CTkButton(frame_left, text="Podmieniające", width=80,
                      command=lambda: self.open_patterns('replace')).pack(side="left", padx=2)

        ctk.CTkLabel(frame_left, text="| Widok:").pack(side="left", padx=10)
        ctk.CTkOptionMenu(frame_left, variable=self.view_mode, values=[VIEW_MODE_TTS, VIEW_MODE_CLEAN],
                          command=self.refresh_ui, width=130).pack(side="left", padx=2)

        ctk.CTkLabel(frame_left, text="| Szukaj:").pack(side="left", padx=10)

        # Wyszukiwarka - rozszerzalna
        self.ent_search = ctk.CTkEntry(frame_left, textvariable=self.search_text, placeholder_text="Filtruj...")
        self.ent_search.pack(side="left", padx=2, fill="x", expand=True)
        self.ent_search.bind("<Return>", self.perform_search)

        ctk.CTkButton(frame_left, text="Szukaj", width=50, command=self.perform_search).pack(side="left", padx=2)
        ctk.CTkButton(frame_left, text="X", width=30, fg_color="gray", command=self.clear_search).pack(side="left",
                                                                                                       padx=2)

        # Prawa strona (Commit)
        frame_right = ctk.CTkFrame(toolbar, fg_color="transparent")
        frame_right.pack(side="right", padx=5)

        ctk.CTkButton(frame_right, text="Commit (Ctrl+K)", fg_color="green", width=120,
                      command=self.commit_changes).pack(side="left", padx=10)

        self.combo_history = ctk.CTkOptionMenu(frame_right, values=["Brak"], command=self.restore_history, width=150)
        self.combo_history.pack(side="left", padx=5)

        self.update_btn = ctk.CTkButton(frame_right, text="Update!", fg_color="#006400", width=80,
                                        command=self._download_update)

    def _bind_shortcuts(self):
        self.bind("<Control-n>", lambda e: self.new_project())
        self.bind("<Control-s>", lambda e: self.save_project())
        self.bind("<Control-k>", lambda e: self.commit_changes())
        self.bind("<Control-g>", lambda e: self.generate_current_line())
        self.bind("<Control-G>", lambda e: self.generate_audio_tts())
        self.bind("<Control-space>", lambda e: self.play_current_line_audio())
        self.bind("<Escape>", lambda e: self.clear_search())

    # --- Project Management ---

    def new_project(self):
        if self.project.has_unsaved_changes:
            if not messagebox.askyesno("Uwaga", "Niezapisane zmiany. Kontynuować?"): return

        # Wybierz plik tekstowy
        txt_path = filedialog.askopenfilename(title="Wybierz napisy", filetypes=[("Tekst", "*.txt *.srt")])
        if not txt_path: return

        # Wybierz folder docelowy dla projektu
        dest_folder = filedialog.askdirectory(title="Wybierz pusty folder na nowy projekt")
        if not dest_folder: return

        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            self.project.create_project(Path(dest_folder), lines)
            self._on_project_loaded()
            self.set_status(f"Utworzono projekt w: {dest_folder}")
        except Exception as e:
            messagebox.showerror("Błąd", str(e))

    def open_project(self, path=None):
        if not path:
            path = filedialog.askdirectory(title="Wybierz folder projektu")
        if not path: return

        try:
            self.project.open_project(Path(path))
            self._on_project_loaded()
            self.set_status(f"Otwarto: {Path(path).name}")
        except Exception as e:
            messagebox.showerror("Błąd", f"Nie można otworzyć projektu:\n{e}")

    def _on_project_loaded(self):
        self._add_recent_project(str(self.project.project_dir))
        self.refresh_editor_from_state()
        self.refresh_ui()

    def save_project(self):
        # W modelu DB/Git zapis jest ciągły lub przy commicie.
        # Ten przycisk może służyć do zapisu samej bazy (ustawień/wzorców) bez commita git.
        self.project.save_data()
        self.set_status("Zapisano dane projektu (DB).")

    def commit_changes(self):
        if self.search_text.get():
            return messagebox.showwarning("Błąd", "Wyczyść filtr przed commitem.")

        # Pobierz tekst z edytora
        raw_text = self.txt_editor.get("1.0", "end-1c")
        new_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

        # Aktualizuj stan w pamięci (reconcile)
        from app.text_processing import reconcile_lines
        self.project.subtitle_lines = reconcile_lines(self.project.subtitle_lines, new_lines)

        # Przygotuj statystyki dla okna dialogowego
        stats = self.project.prepare_commit()

        # Pokaż okno
        CommitDialog(self, stats, lambda: self._do_commit())

    def _do_commit(self):
        self.project.commit("Aktualizacja dialogów z GUI")
        self.set_status("Zatwierdzono zmiany (Git Commit).")

    # --- Single Line Logic (Generate/Play) ---

    def _get_current_line_data(self):
        """Zwraca (SubtitleLine) dla linii pod kursorem."""
        if not self.project.subtitle_lines: return None

        try:
            index = self.txt_editor.index("insert")
            row = int(index.split('.')[0]) - 1  # 0-indexed
        except:
            return None

        query = self.search_text.get().lower()
        lines = self.project.subtitle_lines

        if query:
            visible_indices = [i for i, l in enumerate(lines) if query in l.text.lower()]
            if 0 <= row < len(visible_indices):
                real_idx = visible_indices[row]
                return lines[real_idx]
        else:
            if 0 <= row < len(lines):
                return lines[row]
        return None

    def generate_current_line(self):
        line = self._get_current_line_data()
        if not line: return self.set_status("Nie wybrano linii.")

        if not self.project.audio_dir:
            return messagebox.showwarning("Błąd", "Wybierz katalog audio (Menu -> Audio -> Wybierz katalog).")

        clean_text = self._process_text_for_tts(line.text)
        if not clean_text: return self.set_status("Pusta linia po czyszczeniu.")

        job = GenerationJob(
            project_path=str(self.project.project_path or "Temp"),
            audio_dir=self.project.audio_dir,
            lines_to_generate=[(line.id, clean_text)],
            tts_model_name=self.project.project_config.get('active_tts_model', 'XTTS'),
            tts_config=self.global_config,
            converter_config={}
        )
        self.gen_manager.add_job(job)
        self.set_status(f"Generowanie: {clean_text[:30]}...")
        self.show_queue_window()

    def play_current_line_audio(self):
        line = self._get_current_line_data()
        if not line: return

        if not self.project.audio_dir:
            return messagebox.showwarning("Błąd", "Nie wybrano katalogu audio.")

        # Logika szukania pliku (zachowana, skoro działa poprawnie)
        uuid_filename_ready = f"output1 ({line.id}).ogg"
        uuid_filename_raw = f"output1 ({line.id}).wav"

        legacy_filename_raw = None
        legacy_filename_ready = None

        try:
            line_idx = self.project.subtitle_lines.index(line)
            legacy_filename_raw = f"output1 ({line_idx + 1}).wav"
            legacy_filename_ready = f"output1 ({line_idx + 1}).ogg"
        except ValueError:
            pass

        search_order = [
            self.project.audio_dir / "ready" / uuid_filename_ready,
            self.project.audio_dir / uuid_filename_raw,
        ]

        if legacy_filename_ready:
            search_order.append(self.project.audio_dir / "ready" / legacy_filename_ready)
            search_order.append(self.project.audio_dir / legacy_filename_raw)

        file_to_play = None
        for path in search_order:
            if path and path.exists():
                file_to_play = path
                break

        if file_to_play:
            self.set_status(f"Odtwarzanie: {file_to_play.name}")
            try:
                # Konfiguracja ukrywania okna konsoli na Windows
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    # startupinfo.dwFlags |= subprocess.STARTUPF_USESHOWWINDOW

                # Komenda ffplay:
                # -nodisp: brak okna graficznego (tylko audio)
                # -autoexit: zamknij proces po zakończeniu pliku
                # -hide_banner: mniej śmieci w logach (opcjonalne)
                cmd = ["ffplay", "-nodisp", "-autoexit", "-hide_banner", str(file_to_play)]

                # Uruchomienie w tle (Popen nie blokuje GUI)
                subprocess.Popen(
                    cmd,
                    startupinfo=startupinfo,
                    stdout=subprocess.DEVNULL,  # Przekierowanie wyjścia w nicość
                    stderr=subprocess.DEVNULL
                )
            except FileNotFoundError:
                messagebox.showerror("Błąd",
                                     "Nie znaleziono programu ffplay. Upewnij się, że FFmpeg jest zainstalowany i dodany do PATH.")
            except Exception as e:
                print(f"Błąd odtwarzania: {e}")
                messagebox.showerror("Błąd", f"Nie udało się odtworzyć pliku:\n{e}")
        else:
            self.set_status("Brak pliku audio.")
            if messagebox.askyesno("Brak audio", "Nie znaleziono pliku audio dla tej linii.\nWygenerować teraz?"):
                self.generate_current_line()

    def _process_text_for_tts(self, raw_text):
        rem = [p for p in self.project.custom_remove if p.enabled]
        rep = [p for p in self.project.custom_replace if p.enabled]

        clean = apply_remove_patterns([raw_text], rem)
        if clean:
            return apply_replace_patterns(clean, rep)[0].strip()
        return ""

    # --- Bulk Audio & Export ---

    def generate_audio_tts(self):
        if not self.project.audio_dir: return

        model = self.global_config.get('active_tts_model', 'Nieznany')
        count = len(self.project.subtitle_lines)

        TTSGenerationDialog(self, count, model, self._run_tts_job)

    def _run_tts_job(self, clear_previous):
        if clear_previous:
            # Logika czyszczenia folderu audio
            pass

            # Przygotowanie danych (jak wcześniej, ale używając self.project.patterns_tts itp.)
        # ... logic ...
        self.gen_manager.add_job(...)  # Job creation
        self.show_queue_window()

    def generate_audio_convert(self):
        if not self.project.audio_dir: return

        count = len(list(self.project.audio_dir.glob("*.wav")))  # Uproszczone zliczanie
        ConversionDialog(self, count, self._run_convert_job)

    def _run_convert_job(self, options):
        # options['out1'], options['clear'] ...
        # Tworzenie ConversionJob z uwzględnieniem flag
        # ... logic ...
        self.gen_manager.add_job(...)
        self.show_queue_window()

    def export_game_reader(self):
        self._generic_export("Game Reader", copy_audio=False)

    def export_lektor(self):
        dest = self._generic_export("Lektor", copy_audio=True)
        if dest:
            cfg = {
                "version": "1.0",
                "source_text": "subtitles.txt",
                "audio_folder": "audio",
                "font_size": 24,
                "bg_color": "#000000",
                "text_color": "#FFFFFF"
            }
            with open(dest / "lektor_config.json", "w") as f:
                json.dump(cfg, f, indent=4)

    def _generic_export(self, app_name, copy_audio=False):
        if not self.project.audio_dir:
            messagebox.showwarning("Błąd", "Brak katalogu audio.")
            return None

        dest_str = filedialog.askdirectory(title=f"Eksport dla {app_name}")
        if not dest_str: return None
        dest_path = Path(dest_str)

        lines = self.project.subtitle_lines
        rem_pats = [p for p in self.project.custom_remove if p.enabled]

        clean_lines_text = []
        valid_indices = []

        for i, line in enumerate(lines):
            processed = apply_remove_patterns([line.text], rem_pats)
            if processed:
                clean_lines_text.append(processed[0])
                valid_indices.append(i)

        if not clean_lines_text:
            messagebox.showwarning("Błąd", "Brak linii po oczyszczeniu.")
            return None

        with open(dest_path / "subtitles.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(clean_lines_text))

        audio_dest = dest_path / "audio"
        if copy_audio and audio_dest.exists(): shutil.rmtree(audio_dest)
        audio_dest.mkdir(exist_ok=True)

        ready_dir = self.project.audio_dir / "ready"
        if not ready_dir.exists():
            messagebox.showwarning("Ostrzeżenie", "Folder 'ready' nie istnieje. Używam plików RAW jeśli dostępne.")
            ready_dir = self.project.audio_dir

        success_count = 0
        for seq_idx, line_idx in enumerate(valid_indices):
            line_uuid = lines[line_idx].id

            # Wyszukiwanie pliku źródłowego (UUID lub Index)
            # 1. UUID
            src_file = ready_dir / f"output1 ({line_uuid}).ogg"
            if not src_file.exists():
                src_file = self.project.audio_dir / f"output1 ({line_uuid}).wav"

            # 2. Legacy Index Fallback (jeśli nadal nie znaleziono)
            if not src_file.exists():
                src_file = ready_dir / f"output1 ({line_idx + 1}).ogg"
            if not src_file.exists():
                src_file = self.project.audio_dir / f"output1 ({line_idx + 1}).wav"

            dst_ext = src_file.suffix if src_file.exists() else ".ogg"
            dst_file = audio_dest / f"{seq_idx + 1}{dst_ext}"

            if src_file.exists():
                shutil.copy2(src_file, dst_file)
                success_count += 1
            else:
                print(f"Brak pliku audio dla linii {line_idx + 1} (ID: {line_uuid})")

        messagebox.showinfo("Sukces",
                            f"Wyeksportowano do {dest_path}.\nSkopiowano audio: {success_count}/{len(valid_indices)}")
        return dest_path

    def export_patterns(self, ptype):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if path:
            self.project.export_patterns_to_csv(Path(path), ptype)
            self.set_status("Wyeksportowano wzorce.")

    # --- UI Helpers & Search ---

    def perform_search(self, event=None):
        self.refresh_ui(filter_active=True)

    def clear_search(self):
        self.search_text.set("")
        self.refresh_ui(filter_active=False)

    def refresh_ui(self, event=None, filter_active=False):
        query = self.search_text.get().lower()
        lines = self.project.subtitle_lines

        # Filtrowanie
        if query:
            visible_indices = [i for i, l in enumerate(lines) if query in l.text.lower()]
        else:
            visible_indices = list(range(len(lines)))

        is_filtered = len(visible_indices) < len(lines)

        # Update Editora
        current_state = self.txt_editor._textbox.cget("state")

        if is_filtered:
            # Tryb Filtrowania -> ReadOnly
            self.txt_editor.configure(state="normal")
            self.txt_editor.delete("1.0", "end")
            self.txt_editor.insert("1.0", "\n".join(lines[i].text for i in visible_indices))
            self.txt_editor.configure(state="disabled")
            self.lbl_editor.configure(text=f"EDYTORY (Filtr: {len(visible_indices)})", text_color="orange")
        else:
            # Tryb Normalny -> Editable
            # Odśwież tylko jeśli edytor był wcześniej zablokowany (czyli wychodzimy z filtra)
            # lub jeśli jest pusty (start)
            if current_state == "disabled":
                self.refresh_editor_from_state()
            self.lbl_editor.configure(text="EDYTORY (Robocza)", text_color=("black", "white"))

        # Update Preview
        rem = [p for p in self.project.custom_remove if p.enabled]
        rep = [p for p in self.project.custom_replace if
               p.enabled] if self.view_mode.get() == VIEW_MODE_TTS else []

        out = []
        for idx in visible_indices:
            raw = lines[idx].text
            clean = apply_remove_patterns([raw], rem)
            if clean:
                final = apply_replace_patterns(clean, rep)[0]
                out.append(f"{idx + 1:03} | {final}")
            else:
                out.append(f"{idx + 1:03} | [USUNIĘTA]")

        self.txt_preview.configure(state="normal")
        self.txt_preview.delete("1.0", "end")
        self.txt_preview.insert("1.0", "\n".join(out))
        self.txt_preview.configure(state="disabled")

    def refresh_editor_from_state(self):
        self.txt_editor.configure(state="normal")
        self.txt_editor.delete("1.0", "end")
        self.txt_editor.insert("1.0", self.project.get_raw_text())

    def update_history_combo(self):
        vals = [f"[{i + 1}] {s.description}" for i, s in enumerate(self.project.history)]
        self.combo_history.configure(values=vals or ["Brak"])
        if self.project.current_history_index >= 0:
            self.combo_history.set(vals[self.project.current_history_index])

    def restore_history(self, val):
        if val == "Brak": return
        idx = int(val.split("]")[0][1:]) - 1
        self.project.restore_snapshot(idx)
        self.refresh_editor_from_state()
        self.refresh_ui()

    def set_status(self, text):
        self.lbl_status.configure(text=text)

    # --- Windows & Dialogs ---

    def open_patterns(self, ptype):
        if ptype == 'remove':
            target = self.project.patterns_subtitle
            title = "Lista napisów (Wzorce czyszczące)"
        else:
            target = self.project.patterns_tts
            title = "Lista TTS (Wzorce podmiany)"

        from app.ui_windows import PatternWindow  # Import tu, żeby uniknąć cyklu
        PatternWindow(self, title, target, ptype, lambda: self.refresh_ui())

    def open_global_settings(self):
        SettingsWindow(self, self.project.project_config.get('torch_installed', False), mode='global')

    def open_project_settings(self):
        if not self.project.project_path:
            return messagebox.showwarning("Błąd", "Najpierw otwórz lub zapisz projekt.")
        SettingsWindow(self, False, mode='project')

    def show_queue_window(self):
        GenerationQueueWindow(self)

    def show_about(self):
        AboutWindow(self, APP_VERSION)

    def choose_audio_dir(self):
        d = filedialog.askdirectory()
        if d: self.project.audio_dir = Path(d)

    # --- Config & Updates ---

    def _load_global_config(self):
        if APP_CONFIG_FILE.exists():
            try:
                with open(APP_CONFIG_FILE, "r") as f:
                    self.global_config = json.load(f)
            except:
                self.global_config = {}

    def _add_recent_project(self, path):
        recent = self.global_config.get("recent_projects", [])
        if path in recent: recent.remove(path)
        recent.insert(0, path)
        self.global_config["recent_projects"] = recent[:5]
        self.global_config["last_project"] = path
        with open(APP_CONFIG_FILE, "w") as f:
            json.dump(self.global_config, f, indent=2)
        self._create_menu()

    def _apply_theme(self):
        ctk.set_appearance_mode(self.global_config.get('appearance_mode', 'System'))
        ctk.set_default_color_theme(self.global_config.get('color_theme', 'blue'))

    def _check_for_updates(self):
        if not PACKAGING_AVAILABLE: return
        try:
            url = "https://api.github.com/repos/kpasek/subtitle-studio/releases/latest"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                remote_ver = version.parse(data['tag_name'])
                curr_ver = version.parse(APP_VERSION)
                if remote_ver > curr_ver:
                    self.latest_version_info = data['html_url']
                    self.queue.put(lambda: self.update_btn.pack(side="left", padx=5))
        except:
            pass

    def _download_update(self):
        if self.latest_version_info:
            webbrowser.open(self.latest_version_info)

    def check_queue_loop(self):
        try:
            task = self.queue.get_nowait()
            task()
        except queue.Empty:
            pass
        self.after(100, self.check_queue_loop)

    def on_close(self):
        if self.project.has_unsaved_changes:
            if not messagebox.askyesno("Zamykanie", "Masz niezapisane zmiany. Wyjść?"): return
        self.quit()

    # Helpers
    def open_add_remove_pattern(self, callback):
        PatternEditorWindow(self, 'remove', lambda n, o, t: self._pat_cb(n, self.project.custom_remove, callback),
                            None)

    def open_add_replace_pattern(self, callback):
        PatternEditorWindow(self, 'replace',
                            lambda n, o, t: self._pat_cb(n, self.project.custom_replace, callback), None)

    def _pat_cb(self, new_p, target_list, cb):
        target_list.append(new_p)
        cb()

    def save_global_config(self, data):
        self.global_config.update(data)
        with open(APP_CONFIG_FILE, "w") as f:
            json.dump(self.global_config, f, indent=2)
        self._apply_theme()

    def set_project_config(self, key, val):
        self.project.project_config[key] = val
        self.project.has_unsaved_changes = True


if __name__ == '__main__':
    multiprocessing.freeze_support()
    app = SubtitleStudioApp()
    app.mainloop()