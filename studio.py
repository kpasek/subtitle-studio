import multiprocessing
import os
import shutil
import json
import threading
import webbrowser
import requests
import re
import ctypes
import subprocess
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import queue
from datetime import datetime

# --- CORE IMPORTS ---
from app.project import ProjectManager
from app.text_processing import apply_remove_patterns, apply_replace_patterns
from app.utils import is_installed
from app.settings import SettingsWindow

# --- UI IMPORTS ---
from ui.windows import PatternWindow, AboutWindow
from ui.dialogs import CommitDialog, TTSGenerationDialog, ConversionDialog

# --- AUDIO IMPORTS ---
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

APP_TITLE = "Subtitle Studio 2.3 (Pro)"
APP_VERSION = "2.3.0"
GLOBAL_CONFIG_FILE = Path.home() / ".subtitle_studio_global.json"

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
        self.sync_scroll_enabled = tk.BooleanVar(value=True)  # Domyślnie włączone

        self.global_config = {}
        self.queue = queue.Queue()
        self.latest_version_info = None
        self.update_btn = None
        self.is_scrolling = False  # flaga do sync scrolla

        # Init
        self._load_global_config()
        self._apply_theme()
        self._create_menu()
        self._create_layout()
        self._bind_shortcuts()

        # Background tasks
        self.check_queue_loop()
        threading.Thread(target=self._check_for_updates, daemon=True).start()

        # Auto-open last project
        last_proj = self.global_config.get("last_project")
        if last_proj and os.path.exists(last_proj):
            # Używamy after, żeby GUI zdążyło się narysować
            self.after(500, lambda: self.open_project(Path(last_proj)))

    # --------------------------------------------------------------------------
    # UI CONSTRUCTION
    # --------------------------------------------------------------------------

    def _create_menu(self):
        menubar = tk.Menu(self)

        # --- Plik ---
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Nowy projekt (Ctrl+N)", command=self.new_project)
        file_menu.add_command(label="Otwórz projekt (Folder)", command=self.open_project)

        recent_menu = tk.Menu(file_menu, tearoff=0)
        recent = self.global_config.get("recent_projects", [])
        if not recent:
            recent_menu.add_command(label="(Brak)", state="disabled")
        else:
            for path in recent:
                recent_menu.add_command(label=path, command=lambda p=path: self.open_project(p))
        file_menu.add_cascade(label="Ostatnie projekty", menu=recent_menu)

        file_menu.add_separator()
        file_menu.add_command(label="Ustawienia Projektu", command=self.open_project_settings)
        file_menu.add_command(label="Ustawienia Globalne", command=self.open_global_settings)
        file_menu.add_command(label="Wyjście", command=self.on_close)
        menubar.add_cascade(label="Plik", menu=file_menu)

        # --- Widok ---
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(label="Synchronizuj przewijanie", variable=self.sync_scroll_enabled)
        menubar.add_cascade(label="Widok", menu=view_menu)

        # --- Audio ---
        audio_menu = tk.Menu(menubar, tearoff=0)
        audio_menu.add_command(label="Otwórz folder audio", command=self.open_audio_folder)
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

        # Preview (Lewy)
        frame_left = ctk.CTkFrame(paned)
        paned.add(frame_left)
        ctk.CTkLabel(frame_left, text="PODGLĄD (ReadOnly)", font=("Arial", 12, "bold")).pack(pady=2)
        self.txt_preview = ctk.CTkTextbox(frame_left, state="disabled")
        self.txt_preview.pack(fill="both", expand=True, padx=2, pady=2)

        # Editor (Prawy)
        frame_right = ctk.CTkFrame(paned)
        paned.add(frame_right)
        self.lbl_editor = ctk.CTkLabel(frame_right, text="EDYTORY (Robocza)", font=("Arial", 12, "bold"))
        self.lbl_editor.pack(pady=2)

        self.txt_editor = ctk.CTkTextbox(frame_right)
        self.txt_editor.pack(fill="both", expand=True, padx=2, pady=2)

        # --- SCROLL SYNC SETUP ---
        self._setup_sync_scroll(self.txt_editor, self.txt_preview)
        self._setup_sync_scroll(self.txt_preview, self.txt_editor)

        self.lbl_status = ctk.CTkLabel(self, text="Gotowy", anchor="w")
        self.lbl_status.pack(side="bottom", fill="x", padx=10)

    def _setup_sync_scroll(self, source, target):
        """Synchronizacja scrollowania (hook yview)."""
        # Pobieramy oryginalny yview widgetu tekstowego
        orig_yview = source._textbox.yview

        def new_yview(*args):
            # Wywołaj oryginał
            res = orig_yview(*args)
            # Jeśli włączona synchronizacja i nie jesteśmy w pętli
            if self.sync_scroll_enabled.get() and not self.is_scrolling:
                self.is_scrolling = True
                try:
                    # Przekaż to samo polecenie do drugiego okna
                    target._textbox.yview(*args)
                finally:
                    self.is_scrolling = False
            return res

        # Podmień metodę w instancji
        source._textbox.yview = new_yview

    def _create_toolbar(self, parent):
        toolbar = ctk.CTkFrame(parent, height=40)
        toolbar.pack(fill="x", side="top", padx=5, pady=5)

        # Lewa
        frame_left = ctk.CTkFrame(toolbar, fg_color="transparent")
        frame_left.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(frame_left, text="Wzorce:").pack(side="left", padx=5)
        ctk.CTkButton(frame_left, text="Lista Napisów", width=100,
                      command=lambda: self.open_patterns('remove')).pack(side="left", padx=2)
        ctk.CTkButton(frame_left, text="Lista TTS", width=100,
                      command=lambda: self.open_patterns('replace')).pack(side="left", padx=2)

        ctk.CTkLabel(frame_left, text="| Widok:").pack(side="left", padx=10)
        ctk.CTkOptionMenu(frame_left, variable=self.view_mode, values=[VIEW_MODE_TTS, VIEW_MODE_CLEAN],
                          command=self.refresh_ui, width=130).pack(side="left", padx=2)

        ctk.CTkLabel(frame_left, text="| Szukaj:").pack(side="left", padx=10)
        self.ent_search = ctk.CTkEntry(frame_left, textvariable=self.search_text, placeholder_text="Tekst lub 15*")
        self.ent_search.pack(side="left", padx=2, fill="x", expand=True)
        self.ent_search.bind("<Return>", self.perform_search)

        ctk.CTkButton(frame_left, text="Szukaj", width=50, command=self.perform_search).pack(side="left", padx=2)
        ctk.CTkButton(frame_left, text="X", width=30, fg_color="gray", command=self.clear_search).pack(side="left",
                                                                                                       padx=2)

        # Prawa
        frame_right = ctk.CTkFrame(toolbar, fg_color="transparent")
        frame_right.pack(side="right", padx=5)

        ctk.CTkButton(frame_right, text="Ustawienia", width=80, fg_color="#444",
                      command=self.open_project_settings).pack(side="left", padx=5)

        ctk.CTkButton(frame_right, text="Commit (GIT)", fg_color="green", width=100,
                      command=self.commit_changes).pack(side="left", padx=10)

        self.update_btn = ctk.CTkButton(frame_right, text="Update!", fg_color="#006400", width=80,
                                        command=self._download_update)

    def _bind_shortcuts(self):
        self.bind("<Control-n>", lambda e: self.new_project())
        self.bind("<Control-k>", lambda e: self.commit_changes())
        self.bind("<Control-g>", lambda e: self.generate_current_line())
        self.bind("<Control-G>", lambda e: self.generate_audio_tts())
        self.bind("<Control-space>", lambda e: self.play_current_line_audio())
        self.bind("<Escape>", lambda e: self.clear_search())
        self.bind("<Control-x>", lambda e: self.delete_current_line())

    # --------------------------------------------------------------------------
    # CORE LOGIC
    # --------------------------------------------------------------------------

    def new_project(self):
        if self.project.has_unsaved_changes:
            if not messagebox.askyesno("Uwaga", "Masz niezatwierdzone zmiany. Kontynuować?"): return

        txt_path = filedialog.askopenfilename(title="Wybierz plik z napisami (txt/srt)",
                                              filetypes=[("Tekst", "*.txt *.srt")])
        if not txt_path: return

        messagebox.showinfo("Nowy Projekt", "Wybierz PUSTY folder docelowy.")
        dest_folder = filedialog.askdirectory(title="Folder projektu")
        if not dest_folder: return

        # Opcjonalne sprawdzenie czy folder pusty
        dest_path = Path(dest_folder)
        if any(dest_path.iterdir()):
            if not messagebox.askyesno("Folder niepusty",
                                       "Wybrany folder nie jest pusty. Czy na pewno chcesz w nim utworzyć projekt?"):
                return

        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Tworzymy projekt (importując audio jeśli istnieje w źródle)
            self.project.create_project(Path(dest_folder), lines, source_txt_path=Path(txt_path))

            # Przypisz domyślny model globalny
            def_model = self.global_config.get("default_tts_model", "XTTS")
            self.project.set_setting("active_tts_model", def_model)

            self._project_loaded_action()
            self.set_status(f"Utworzono projekt w: {Path(dest_folder).name}")

        except Exception as e:
            messagebox.showerror("Błąd", str(e))

    def open_project(self, path=None):
        if self.project.has_unsaved_changes:
            if not messagebox.askyesno("Uwaga", "Niezapisane zmiany. Porzucić?"): return

        if not path:
            path = filedialog.askdirectory(title="Wybierz folder projektu")
        if not path: return

        path_obj = Path(path)
        try:
            self.project.open_project(path_obj)
            self._project_loaded_action()
            self.set_status(f"Wczytano projekt: {path_obj.name}")
        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się otworzyć projektu:\n{e}")

    def _project_loaded_action(self):
        self._add_recent_project(str(self.project.project_dir))
        self.refresh_editor_from_state()
        self.refresh_ui()

    def commit_changes(self):
        if not self.project.project_dir: return
        if self.search_text.get():
            messagebox.showwarning("Uwaga", "Wyczyść filtr wyszukiwania przed commitem.")
            return

        # Pobranie tekstu z GUI
        raw_text = self.txt_editor.get("1.0", "end-1c")
        new_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

        # Aktualizacja modelu (reconcile)
        from app.text_processing import reconcile_lines
        self.project.subtitle_lines = reconcile_lines(self.project.subtitle_lines, new_lines)

        # Statystyki diffa
        stats = self.project.prepare_commit()

        # Dialog
        CommitDialog(self, stats, lambda: self._do_commit())

    def _do_commit(self):
        try:
            self.project.commit("Update from Studio GUI")
            self.set_status("Zatwierdzono zmiany (Git Commit).")
        except Exception as e:
            messagebox.showerror("Błąd Git", str(e))

    def delete_current_line(self):
        """Usuwa aktualnie wybraną linię."""
        line = self._get_current_line_data()
        if not line: return

        if messagebox.askyesno("Usuń linię", f"Czy usunąć linię:\n{line.text[:50]}...?"):
            self.project.delete_line(line.id)
            self.refresh_ui()
            self.set_status("Usunięto linię.")

    # --------------------------------------------------------------------------
    # AUDIO & EXPORT
    # --------------------------------------------------------------------------

    def generate_audio_tts(self):
        if not self.project.audio_dir:
            return messagebox.showwarning("Info", "Brak otwartego projektu.")

        # Pobieramy model z ustawień projektu
        model = self.project.get_setting("active_tts_model", "XTTS")
        count = len(self.project.subtitle_lines)

        TTSGenerationDialog(self, count, model, self._run_tts_job)

    def _run_tts_job(self, clear_previous):
        if clear_previous:
            # Tu można dodać logikę czyszczenia (deleter.py)
            pass

        lines_data = []
        rem = [p for p in self.project.patterns_subtitle if p.enabled]
        rep = [p for p in self.project.patterns_tts if p.enabled]

        for line in self.project.subtitle_lines:
            clean = apply_remove_patterns([line.text], rem)
            if clean:
                final = apply_replace_patterns(clean, rep)[0].strip()
                if final:
                    lines_data.append((line.id, final))

        if not lines_data:
            return messagebox.showinfo("Info", "Brak linii po przefiltrowaniu.")

        # Pobieramy model z projektu do Joba
        model = self.project.get_setting("active_tts_model", "XTTS")

        job = GenerationJob(
            project_path=str(self.project.project_dir),
            audio_dir=self.project.audio_dir,
            lines_to_generate=lines_data,
            tts_model_name=model,
            tts_config=self.global_config,
            converter_config={}
        )
        self.gen_manager.add_job(job)
        self.show_queue_window()

    def generate_audio_convert(self):
        if not self.project.audio_dir: return
        count = len(list(self.project.audio_dir.glob("output1 (*).wav")))

        filters = self.global_config.get('ffmpeg_filters', {})
        ConversionDialog(self, count, filters, self._run_convert_job)

    def _run_convert_job(self, options):
        # options: out1, out2, clear
        config = {
            'base_audio_speed': self.project.get_setting('base_audio_speed', 1.1),
            'conversion_workers': self.global_config.get('conversion_workers', 4),
            'ffmpeg_filters': self.global_config.get('ffmpeg_filters', {}),
            'generate_out1': options['out1'],
            'generate_out2': options['out2'],
            'clear_ready': options['clear']
        }

        job = ConversionJob(
            project_path=str(self.project.project_dir),
            audio_dir=self.project.audio_dir,
            converter_config=config
        )
        self.gen_manager.add_job(job)
        self.show_queue_window()

    def generate_current_line(self):
        line = self._get_current_line_data()
        if not line: return self.set_status("Nie wybrano linii.")

        rem = [p for p in self.project.patterns_subtitle if p.enabled]
        rep = [p for p in self.project.patterns_tts if p.enabled]
        clean = apply_remove_patterns([line.text], rem)

        if not clean: return self.set_status("Pusta linia.")
        final = apply_replace_patterns(clean, rep)[0].strip()

        model = self.project.get_setting("active_tts_model", "XTTS")

        job = GenerationJob(
            project_path=str(self.project.project_dir),
            audio_dir=self.project.audio_dir,
            lines_to_generate=[(line.id, final)],
            tts_model_name=model,
            tts_config=self.global_config,
            converter_config={}
        )
        self.gen_manager.add_job(job)
        self.show_queue_window()

    def play_current_line_audio(self):
        line = self._get_current_line_data()
        if not line: return
        if not self.project.audio_dir: return

        # Szukamy po UUID
        base_name = f"output1 ({line.id})"
        search_paths = [
            self.project.audio_dir / "ready" / f"{base_name}.ogg",
            self.project.audio_dir / f"{base_name}.wav"
        ]

        file_to_play = next((p for p in search_paths if p.exists()), None)

        if file_to_play:
            self.set_status(f"Odtwarzanie: {file_to_play.name}")
            try:
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTUPF_USESHOWWINDOW

                subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-hide_banner", str(file_to_play)],
                    startupinfo=startupinfo,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception as e:
                messagebox.showerror("Błąd", f"Błąd odtwarzania (ffplay):\n{e}")
        else:
            if messagebox.askyesno("Brak audio", "Nie znaleziono pliku. Wygenerować?"):
                self.generate_current_line()

    # --------------------------------------------------------------------------
    # EXPORT
    # --------------------------------------------------------------------------

    def export_game_reader(self):
        self._run_export("Game Reader", copy_audio=False)

    def export_lektor(self):
        path = self._run_export("Lektor", copy_audio=True)
        if path:
            with open(path / "lektor_config.json", "w") as f:
                json.dump({"version": "1.0", "source": "subtitles.txt"}, f)

    def _run_export(self, name, copy_audio):
        if not self.project.project_dir: return None

        dest = filedialog.askdirectory(title=f"Eksport dla {name}")
        if not dest: return None
        dest_path = Path(dest)

        # 1. Tekst
        lines = self.project.subtitle_lines
        rem = [p for p in self.project.patterns_subtitle if p.enabled]

        final_lines = []
        valid_indices = []

        for i, line in enumerate(lines):
            clean = apply_remove_patterns([line.text], rem)
            if clean:
                final_lines.append(clean[0])
                valid_indices.append(i)

        with open(dest_path / "subtitles.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(final_lines))

        # 2. Audio
        if copy_audio:
            (dest_path / "audio").mkdir(exist_ok=True)

        ready_dir = self.project.audio_dir / "ready"
        count = 0

        for seq, original_idx in enumerate(valid_indices):
            uuid = lines[original_idx].id
            src = ready_dir / f"output1 ({uuid}).ogg"

            if src.exists():
                dst_name = f"{seq + 1}.ogg"
                # Zawsze kopiuj, nawet dla GR, bo nazwy muszą być sekwencyjne
                shutil.copy2(src, dest_path / "audio" / dst_name)
                count += 1

        messagebox.showinfo("Eksport", f"Zakończono.\nLinii: {len(final_lines)}\nAudio: {count}")
        return dest_path

    # --------------------------------------------------------------------------
    # UI UPDATE & HELPERS
    # --------------------------------------------------------------------------

    def refresh_ui(self, event=None, filter_active=False):
        if not self.project.subtitle_lines:
            self._clear_editors()
            return

        query = self.search_text.get().lower()
        lines = self.project.subtitle_lines

        visible_indices = []

        # WYSZUKIWARKA
        if query:
            # Wildcard numeru (np. 15*)
            if re.match(r"^\d+\*?$", query):
                prefix = query.replace("*", "")
                for i, l in enumerate(lines):
                    if str(i + 1).startswith(prefix):
                        visible_indices.append(i)
            else:
                # Tekst
                visible_indices = [i for i, l in enumerate(lines) if query in l.text.lower()]
        else:
            visible_indices = list(range(len(lines)))

        is_filtered = len(visible_indices) < len(lines)

        # Wyłącz sync podczas update
        was_sync = self.sync_scroll_enabled.get()
        self.sync_scroll_enabled.set(False)

        try:
            self._update_editor_content(visible_indices, is_filtered)
            self._update_preview_content(visible_indices)
        finally:
            self.sync_scroll_enabled.set(was_sync)

        if is_filtered:
            self.lbl_editor.configure(text=f"EDYTORY (Filtr: {len(visible_indices)})", text_color="orange")
        else:
            self.lbl_editor.configure(text="EDYTORY (Robocza)", text_color=("black", "white"))

    def _update_editor_content(self, indices, is_filtered):
        # Pobieramy pełny tekst
        lines_text = "\n".join(self.project.subtitle_lines[i].text for i in indices)

        self.txt_editor.configure(state="normal")
        self.txt_editor.delete("1.0", "end")
        self.txt_editor.insert("1.0", lines_text)

        if is_filtered:
            self.txt_editor.configure(state="disabled")

    def _update_preview_content(self, indices):
        rem = [p for p in self.project.patterns_subtitle if p.enabled]
        rep = [p for p in self.project.patterns_tts if p.enabled] if self.view_mode.get() == VIEW_MODE_TTS else []

        out = []
        for idx in indices:
            raw = self.project.subtitle_lines[idx].text
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

    def _clear_editors(self):
        self.txt_editor.configure(state="normal")
        self.txt_editor.delete("1.0", "end")
        self.txt_preview.configure(state="normal")
        self.txt_preview.delete("1.0", "end")
        self.txt_preview.configure(state="disabled")
        self.lbl_editor.configure(text="EDYTORY (Pusty projekt)")

    def _get_current_line_data(self):
        if not self.project.subtitle_lines: return None
        try:
            index = self.txt_editor.index("insert")
            row = int(index.split('.')[0]) - 1
        except:
            return None

        query = self.search_text.get().lower()
        lines = self.project.subtitle_lines
        visible = []

        if query:
            if re.match(r"^\d+\*?$", query):
                prefix = query.replace("*", "")
                visible = [i for i, l in enumerate(lines) if str(i + 1).startswith(prefix)]
            else:
                visible = [i for i, l in enumerate(lines) if query in l.text.lower()]
        else:
            visible = range(len(lines))

        if 0 <= row < len(visible):
            return lines[visible[row]]
        return None

    def set_status(self, text):
        self.lbl_status.configure(text=text)

    def apply_theme_settings(self):
        self._apply_theme()

    def perform_search(self, event=None):
        self.refresh_ui(filter_active=True)

    def clear_search(self, event=None):
        self.search_text.set("")
        self.refresh_ui()

    def open_patterns(self, ptype):
        target_list = self.project.patterns_subtitle if ptype == 'remove' else self.project.patterns_tts
        type_key = 'subtitle' if ptype == 'remove' else 'tts'
        title = "Lista Napisów" if ptype == 'remove' else "Lista TTS"
        PatternWindow(self, title, target_list, type_key, lambda: self.refresh_ui())

    def open_project_settings(self):
        if not self.project.project_dir:
            return messagebox.showwarning("Błąd", "Brak otwartego projektu.")
        SettingsWindow(self, False, mode='project')

    def open_global_settings(self):
        SettingsWindow(self, False, mode='global')

    def open_audio_folder(self):
        if self.project.audio_dir: os.startfile(self.project.audio_dir)

    def show_queue_window(self):
        GenerationQueueWindow(self)

    def show_about(self):
        AboutWindow(self, APP_VERSION)

    def _load_global_config(self):
        if GLOBAL_CONFIG_FILE.exists():
            try:
                with open(GLOBAL_CONFIG_FILE, "r") as f:
                    self.global_config = json.load(f)
            except:
                self.global_config = {}
        # Defaults fallback
        from app.settings import DEFAULT_CONFIG
        for k, v in DEFAULT_CONFIG.items():
            if k not in self.global_config: self.global_config[k] = v

    def _add_recent_project(self, path):
        recent = self.global_config.get("recent_projects", [])
        if path in recent: recent.remove(path)
        recent.insert(0, path)
        self.global_config["recent_projects"] = recent[:5]
        self.global_config["last_project"] = path
        with open(GLOBAL_CONFIG_FILE, "w") as f:
            json.dump(self.global_config, f, indent=2)
        self._create_menu()

    def _apply_theme(self):
        ctk.set_appearance_mode(self.global_config.get('appearance_mode', 'System'))

    def _check_for_updates(self):
        if not PACKAGING_AVAILABLE: return
        try:
            url = "https://api.github.com/repos/kpasek/subtitle-studio/releases/latest"
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if version.parse(data['tag_name']) > version.parse(APP_VERSION):
                    self.latest_version_info = data['html_url']
                    self.queue.put(lambda: self.update_btn.pack(side="left", padx=5))
        except:
            pass

    def _download_update(self):
        if self.latest_version_info: webbrowser.open(self.latest_version_info)

    def check_queue_loop(self):
        try:
            task = self.queue.get_nowait()
            task()
        except queue.Empty:
            pass
        self.after(100, self.check_queue_loop)

    def on_close(self):
        if self.project.has_unsaved_changes:
            if not messagebox.askyesno("Wyjście", "Masz niezatwierdzone zmiany. Wyjść?"): return
        self.project.close()
        self.quit()

    def refresh_editor_from_state(self):
        self.txt_editor.configure(state="normal")
        self.txt_editor.delete("1.0", "end")
        if self.project.subtitle_lines:
            self.txt_editor.insert("1.0", "\n".join(l.text for l in self.project.subtitle_lines))

    # Compatibility Helpers
    def open_add_remove_pattern(self, callback):
        PatternEditorWindow(self, 'remove', lambda n, o, t: self._pat_cb(n, self.project.patterns_subtitle, callback),
                            None)

    def open_add_replace_pattern(self, callback):
        PatternEditorWindow(self, 'replace', lambda n, o, t: self._pat_cb(n, self.project.patterns_tts, callback), None)

    def _pat_cb(self, new_p, target_list, cb):
        target_list.append(new_p)
        self.project.save_data()
        cb()

    def save_global_config(self, data):
        self.global_config.update(data)
        with open(GLOBAL_CONFIG_FILE, "w") as f:
            json.dump(self.global_config, f, indent=2)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    app = SubtitleStudioApp()
    app.mainloop()