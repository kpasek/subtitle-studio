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
from ui.windows import PatternWindow, AboutWindow, AppliedPatternsPreviewWindow, RecentProjectsWindow
from ui.dialogs import CommitDialog, TTSGenerationDialog, ConversionDialog

# --- AUDIO IMPORTS ---
from audio.generation_manager import GenerationManager, GenerationJob, ConversionJob
from audio.pattern_editor import PatternEditorWindow
from audio.generation_queue import GenerationQueueWindow
from audio.deleter import AudioDeleterWindow
from audio.audio_renamer import AudioRenameWindow
from audio.legacy_importer import LegacyImporterWindow

try:
    from packaging import version

    PACKAGING_AVAILABLE = True
except ImportError:
    PACKAGING_AVAILABLE = False

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

APP_TITLE = "Subtitle Studio 2.4 (New DB)"
APP_VERSION = "2.4.0"
GLOBAL_CONFIG_FILE = Path.home() / ".subtitle_studio_global.json"

VIEW_MODE_TTS = "Widok: TTS (Lektor)"
VIEW_MODE_CLEAN = "Widok: Napisy (Game Reader)"


class SubtitleStudioApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.title(APP_TITLE)
        self.geometry("1600x900")

        self.project = ProjectManager()
        self.gen_manager = GenerationManager.get_instance()

        self.view_mode = tk.StringVar(value=VIEW_MODE_TTS)
        self.search_text = tk.StringVar()
        self.sync_scroll_enabled = tk.BooleanVar(value=True)

        self.global_config = {}
        self.queue = queue.Queue()
        self.latest_version_info = None
        self.update_btn = None

        self._load_global_config()
        self._apply_theme()
        self._create_menu()
        self._create_layout()
        self._bind_shortcuts()

        saved_sync = self.global_config.get("sync_scroll", True)
        self.sync_scroll_enabled = tk.BooleanVar(value=saved_sync)

        self.check_queue_loop()
        threading.Thread(target=self._check_for_updates, daemon=True).start()
        self.after(500, self._auto_load_last_project)

    def _auto_load_last_project(self):
        last_proj = self.global_config.get("last_project")
        if last_proj and os.path.exists(last_proj):
            self.open_project(Path(last_proj))

    # --------------------------------------------------------------------------
    # UI CONSTRUCTION
    # --------------------------------------------------------------------------

    def _create_menu(self):
        menubar = tk.Menu(self)
        # --- Plik ---
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Nowy projekt (Ctrl+N)", command=self.new_project)
        file_menu.add_command(label="Otwórz projekt (Ctrl+O)", command=self.open_project)
        file_menu.add_command(label="Ostatnie projekty (Ctrl+E)", command=self.open_recent_projects_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Ustawienia Projektu", command=self.open_project_settings)
        file_menu.add_command(label="Ustawienia Globalne", command=self.open_global_settings)
        file_menu.add_command(label="Wyjście", command=self.on_close)
        menubar.add_cascade(label="Plik", menu=file_menu)

        # --- Widok ---
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(label="Synchronizuj widoki (kursor)", variable=self.sync_scroll_enabled)
        menubar.add_cascade(label="Widok", menu=view_menu)

        # --- Audio ---
        audio_menu = tk.Menu(menubar, tearoff=0)
        audio_menu.add_command(label="Otwórz folder audio", command=self.open_audio_folder)
        audio_menu.add_command(label="Importuj katalog audio (Legacy)", command=self.import_audio_folder)
        audio_menu.add_separator()
        audio_menu.add_command(label="Generuj wszystko TTS (Ctrl+Shift+G)", command=self.generate_audio_tts)
        audio_menu.add_command(label="Konwertuj audio (WAV->OGG)", command=self.generate_audio_convert)
        audio_menu.add_separator()
        audio_menu.add_command(label="Masowe usuwanie plików", command=self.open_mass_delete)
        audio_menu.add_command(label="Przesuń/Dopasuj pliki audio", command=self.open_audio_renamer)
        audio_menu.add_separator()
        audio_menu.add_command(label="Generuj aktualną linię (Ctrl+G)", command=self.generate_current_line)
        audio_menu.add_command(label="Odtwórz aktualną linię (Ctrl+Spacja)", command=self.play_current_line_audio)
        audio_menu.add_command(label="Usuń duplikaty", command=self.open_remove_duplicates_dialog)  # NOWE
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

        self.paned = tk.PanedWindow(container, orient=tk.HORIZONTAL, sashwidth=6, bg="#2b2b2b")
        self.paned.pack(fill="both", expand=True, padx=5, pady=5)

        # Preview (Lewy) - Tu pokażemy Oryginał
        frame_left = ctk.CTkFrame(self.paned)
        self.paned.add(frame_left)
        ctk.CTkLabel(frame_left, text="ORYGINAŁ (Podgląd)", font=("Arial", 12, "bold")).pack(pady=2)
        self.txt_preview = ctk.CTkTextbox(frame_left, state="disabled")
        self.txt_preview.pack(fill="both", expand=True, padx=2, pady=2)

        # Editor (Prawy) - Tu edytujemy w zależności od trybu
        frame_right = ctk.CTkFrame(self.paned)
        self.paned.add(frame_right)
        self.lbl_editor = ctk.CTkLabel(frame_right, text="EDYCJA", font=("Arial", 12, "bold"))
        self.lbl_editor.pack(pady=2)

        editor_container = ctk.CTkFrame(frame_right, fg_color="transparent")
        editor_container.pack(fill="both", expand=True, padx=2, pady=2)

        self.txt_linenums = ctk.CTkTextbox(editor_container, width=60, state="disabled", text_color="gray",
                                           fg_color="transparent", activate_scrollbars=False)
        self.txt_linenums.pack(side="left", fill="y", padx=(0, 2))

        self.txt_editor = ctk.CTkTextbox(editor_container)
        self.txt_editor.pack(side="left", fill="both", expand=True)
        self.txt_editor._textbox.config(yscrollcommand=self._on_editor_scroll)

        self.after(100, lambda: self.paned.sash_place(0, 530, 0))
        self._setup_cursor_sync()

        self.sync_scroll_enabled.trace_add("write", self._save_sync_setting)
        self.lbl_status = ctk.CTkLabel(self, text="Gotowy", anchor="w")
        self.lbl_status.pack(side="bottom", fill="x", padx=10)

    def _setup_cursor_sync(self):
        """Synchronizacja na podstawie pozycji kursora (insert)."""

        def sync_to_cursor(event):
            if not self.sync_scroll_enabled.get(): return

            # Określ źródło i cel
            if event.widget == self.txt_editor._textbox:
                source = self.txt_editor
                target = self.txt_preview
            elif event.widget == self.txt_preview._textbox:
                source = self.txt_preview
                target = self.txt_editor
            else:
                return

            try:
                # Pobierz numer linii kursora
                cursor_index = source.index("insert")
                line_num = int(cursor_index.split('.')[0])

                # Zbuduj indeks dla drugiego okna (poczatek linii)
                target_index = f"{line_num}.0"

                # Przewiń tak, aby linia była widoczna (najlepiej wyśrodkowana)
                # 'see' zapewnia widoczność, ale nie centruje idealnie.
                # Można użyć hacku:
                target.see(target_index)

                # Opcjonalne centrowanie (bardziej zaawansowane):
                # count_lines = int(target.index('end-1c').split('.')[0])
                # fraction = (line_num - 10) / count_lines # -10 jako offset
                # target.yview_moveto(max(0, fraction))

            except Exception:
                pass

        # Podpinamy pod kliknięcia myszką i puszczenie klawiszy (strzałki)
        for t in [self.txt_editor._textbox, self.txt_preview._textbox]:
            t.bind("<ButtonRelease-1>", sync_to_cursor)
            t.bind("<KeyRelease>", sync_to_cursor)

    def _create_toolbar(self, parent):
        toolbar = ctk.CTkFrame(parent, height=40)
        toolbar.pack(fill="x", side="top", padx=5, pady=5)

        frame_left = ctk.CTkFrame(toolbar, fg_color="transparent")
        frame_left.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(frame_left, text="Wzorce:").pack(side="left", padx=5)
        ctk.CTkButton(frame_left, text="Lista Napisów", width=100, command=lambda: self.open_patterns('remove')).pack(
            side="left", padx=2)
        ctk.CTkButton(frame_left, text="Lista TTS", width=100, command=lambda: self.open_patterns('replace')).pack(
            side="left", padx=2)

        ctk.CTkLabel(frame_left, text="|").pack(side="left", padx=10)
        ctk.CTkOptionMenu(frame_left, variable=self.view_mode, values=[VIEW_MODE_TTS, VIEW_MODE_CLEAN],
                          command=self.refresh_ui, width=180).pack(side="left", padx=2)

        frame_right = ctk.CTkFrame(toolbar, fg_color="transparent")
        frame_right.pack(side="right", padx=5)

        ctk.CTkButton(frame_right, text="Zatwierdź i Przelicz", fg_color="green", width=140,
                      command=self.commit_changes).pack(side="left", padx=10)

    def _bind_shortcuts(self):
        self.bind("<Control-n>", lambda e: self.new_project())
        self.bind("<Control-o>", lambda e: self.open_project())
        self.bind("<Control-e>", lambda e: self.open_recent_projects_dialog())
        self.bind("<Control-k>", lambda e: self.commit_changes())

        self.bind("<Control-g>", lambda e: self.generate_current_line())
        self.bind("<Control-G>", lambda e: self.generate_audio_tts())
        self.bind("<Control-space>", lambda e: self.play_current_line_audio())

        self.bind("<Escape>", lambda e: self.clear_search())
        self.bind("<Control-f>", lambda e: self.ent_search.focus_set())
        self.bind("<Alt-s>", lambda e: self.sync_scroll_enabled.set(not self.sync_scroll_enabled.get()))

        self.bind("<Control-x>", lambda e: self.delete_current_line())

    # --------------------------------------------------------------------------
    # CORE LOGIC
    # --------------------------------------------------------------------------

    def new_project(self):
        txt_path = filedialog.askopenfilename(title="Wybierz plik z napisami", filetypes=[("Tekst", "*.txt *.srt")])
        if not txt_path: return

        dest_folder = filedialog.askdirectory(title="Wybierz PUSTY folder projektu")
        if not dest_folder: return

        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Nowa logika tworzenia projektu
            self.project.create_project(Path(dest_folder), lines, source_txt_path=Path(txt_path))

            self._project_loaded_action()
            self.set_status(f"Utworzono projekt (ID-based): {Path(dest_folder).name}")
        except Exception as e:
            messagebox.showerror("Błąd", str(e))

    def open_project(self, path=None):
        if self.project.has_unsaved_changes:
            if not messagebox.askyesno("Uwaga", "Niezapisane zmiany. Porzucić?"): return

        if not path:
            path = filedialog.askdirectory(title="Wybierz folder projektu")
        if not path: return

        path_obj = Path(path) if isinstance(path, str) else path

        try:
            self.project.open_project(path_obj)
            self._project_loaded_action()
            self.set_status(f"Wczytano projekt: {path_obj.name}")
        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się otworzyć projektu:\n{e}")

    def open_recent_projects_dialog(self):
        win = RecentProjectsWindow(self)
        # Te metody zapewniają poprawne wyświetlanie na wierzchu
        win.wait_visibility()
        win.lift()
        win.attributes("-topmost", True)

    def open_recent_project(self):
        self.open_recent_projects_dialog()

    def _project_loaded_action(self):
        self._add_recent_project(str(self.project.project_dir))
        self.refresh_editor_from_state()
        self.refresh_ui()

    def commit_changes(self):
        """
        1. Zbiera tekst z edytora i aktualizuje odpowiednie pole w bazie (MANUAL).
        2. Uruchamia aplikowanie wzorców (PATTERN) na zaktualizowanym tekście.
        3. Zapisuje zmiany do bazy.
        """
        if not self.project.project_dir: return

        # 1. Pobierz tekst z edytora
        raw_text = self.txt_editor.get("1.0", "end-1c")
        editor_lines = raw_text.splitlines()

        # Sprawdzenie spójności liczby linii
        if len(editor_lines) != len(self.project.subtitle_lines):
            messagebox.showerror("Błąd",
                                 "Liczba linii w edytorze nie zgadza się z liczbą linii w bazie.\nNie można zapisać zmian masowo.")
            return

        mode = 'tts' if self.view_mode.get() == VIEW_MODE_TTS else 'subtitle'

        # 2. Aktualizacja ręcznych zmian w pamięci
        for i, text in enumerate(editor_lines):
            self.project.update_manual_edit(i, text, mode)

        # 3. Zastosowanie wzorców i zapis do DB
        # Zgodnie z wymaganiem: "Zatwierdzanie zmian ma stosować dodane wzorce... i oznaczyć jako zastosowane"
        changed_count = self.project.apply_patterns_and_save(mode)

        self.set_status(f"Zapisano zmiany. Wzorce zmieniły {changed_count} linii.")
        self.refresh_ui()

    def _do_commit(self):
        try:
            self.project.commit("Zatwierdzono zmiany z GUI")
            self.set_status("Zmiany zostały pomyślnie zatwierdzone.")
        except Exception as e:
            messagebox.showerror("Błąd zapisu", str(e))

    def delete_current_line(self):
        line = self._get_current_line_data()
        if not line: return
        if messagebox.askyesno("Usuń linię", f"Czy usunąć linię:\n{line.text[:50]}...?"):
            self.project.delete_line(line.id)
            self.refresh_ui()
            self.set_status("Usunięto linię.")

    # --------------------------------------------------------------------------
    # AUDIO & EXPORT
    # --------------------------------------------------------------------------
    def import_audio_folder(self):
        if not self.project.project_dir:
            messagebox.showwarning("Błąd", "Najpierw otwórz projekt.")
            return
        win = LegacyImporterWindow(self, self.project)
        win.wait_visibility()
        win.lift()

    def generate_audio_tts(self):
        if not self.project.audio_dir:
            return messagebox.showwarning("Info", "Brak otwartego projektu.")
        model = self.project.get_setting("active_tts_model", "XTTS")
        count = len(self.project.subtitle_lines)
        TTSGenerationDialog(self, count, model, self._run_tts_job)

    def _run_tts_job(self, clear_previous):
        lines_data = []
        rem = [p for p in self.project.patterns_subtitle if p.enabled]
        rep = [p for p in self.project.patterns_tts if p.enabled]

        for line in self.project.subtitle_lines:
            if line.tts_override is not None:
                final = line.tts_override.strip()
                if final:
                    lines_data.append((line.id, final))
                continue
            clean = apply_remove_patterns([line.text], rem)
            if clean:
                final = apply_replace_patterns(clean, rep)[0].strip()
                if final:
                    lines_data.append((line.id, final))

        if not lines_data:
            return messagebox.showinfo("Info", "Brak linii po przefiltrowaniu.")

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
        # Pobieranie filtrów z projektu, fallback do globalnych
        filters = self.project.get_setting('ffmpeg_filters', self.global_config.get('ffmpeg_filters', {}))

        ConversionDialog(self, count, filters, self._run_convert_job)

    def _run_convert_job(self, options):
        config = {
            'base_audio_speed': self.project.get_setting('base_audio_speed', 1.1),
            'conversion_workers': self.global_config.get('conversion_workers', 4),
            'ffmpeg_filters': options['filters'],
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
        # Pobranie ID linii z pozycji kursora
        line = self._get_current_line_data()
        if not line: return

        # Tekst do generowania to zawsze tts_text (finalny)
        text_to_speak = line.tts_text
        if not text_to_speak.strip():
            return messagebox.showinfo("Info", "Pusty tekst TTS.")

        model = self.project.get_setting("active_tts_model", "XTTS")

        # Job generowania
        job = GenerationJob(
            project_path=str(self.project.project_dir),
            audio_dir=self.project.audio_dir,
            lines_to_generate=[(line.id, text_to_speak)],  # ID teraz jest int
            tts_model_name=model,
            tts_config=self.global_config,
            converter_config={}
        )
        self.gen_manager.add_job(job)
        self.show_queue_window()

    def play_current_line_audio(self):
        line = self._get_current_line_data()
        if not line: return

        # Szukamy [id].wav lub [id].ogg
        # Pliki mogą być w głównym folderze lub w ready (po konwersji)
        candidates = [
            self.project.audio_dir / f"{line.id}.wav",
            self.project.audio_dir / f"{line.id}.mp3",
            self.project.audio_dir / "ready" / f"{line.id}.ogg"
        ]

        found = next((f for f in candidates if f.exists()), None)

        if found:
            self.set_status(f"Odtwarzanie: {found.name}")
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTUPF_USESHOWWINDOW
                subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-hide_banner", str(found)],
                                 startupinfo=si, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(e)
        else:
            self.set_status("Brak pliku audio.")

    def open_mass_delete(self):
        if not self.project.project_dir: return
        texts = [l.text for l in self.project.subtitle_lines]
        win = AudioDeleterWindow(self, texts, str(self.project.audio_dir))
        win.wait_visibility()
        win.lift()

    def open_audio_renamer(self):
        if not self.project.audio_dir: return
        win = AudioRenameWindow(self, self.project.audio_dir)
        win.wait_visibility()
        win.lift()

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

        if copy_audio:
            (dest_path / "audio").mkdir(exist_ok=True)

        ready_dir = self.project.audio_dir / "ready"
        count = 0

        for seq, original_idx in enumerate(valid_indices):
            uuid = lines[original_idx].id
            src = ready_dir / f"output1 ({uuid}).ogg"

            if src.exists():
                dst_name = f"{seq + 1}.ogg"
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

        lines = self.project.subtitle_lines
        # Tu można dodać logikę filtrowania (search), na razie proste odświeżenie całości
        indices = range(len(lines))

        self.txt_editor.configure(state="normal")
        self.txt_linenums.configure(state="normal")
        self.txt_preview.configure(state="normal")

        self.txt_editor.delete("1.0", "end")
        self.txt_linenums.delete("1.0", "end")
        self.txt_preview.delete("1.0", "end")

        editor_content = []
        preview_content = []
        nums = []

        is_tts_view = (self.view_mode.get() == VIEW_MODE_TTS)
        mode_label = "TTS" if is_tts_view else "NAPISY"
        self.lbl_editor.configure(text=f"EDYCJA: {mode_label}")

        for i in indices:
            line = lines[i]

            # Oryginał zawsze w podglądzie
            preview_content.append(f"{line.id} | {line.original_text}")
            nums.append(str(line.id))

            # Edytor w zależności od trybu
            if is_tts_view:
                editor_content.append(line.tts_text)
            else:
                editor_content.append(line.subtitle_text)

        self.txt_preview.insert("1.0", "\n".join(preview_content))
        self.txt_editor.insert("1.0", "\n".join(editor_content))
        self.txt_linenums.insert("1.0", "\n".join(nums))

        self.txt_editor.configure(state="normal")  # User can edit
        self.txt_preview.configure(state="disabled")
        self.txt_linenums.configure(state="disabled")

    def _update_editor_content(self, indices, is_filtered):
        self.txt_editor.configure(state="normal")
        self.txt_linenums.configure(state="normal")

        self.txt_editor.delete("1.0", "end")
        self.txt_linenums.delete("1.0", "end")

        content_lines = []
        linenum_lines = []

        rem_patterns = [p for p in self.project.patterns_subtitle if p.enabled]
        rep_patterns = [p for p in self.project.patterns_tts if p.enabled]

        for i in indices:
            line = self.project.subtitle_lines[i]

            # Jeśli tryb TTS - pokaż override lub wygenerowany tekst
            if self.view_mode.get() == VIEW_MODE_TTS:
                if line.tts_override is not None:
                    content_lines.append(line.tts_override)
                else:
                    # Generuj live
                    clean = apply_remove_patterns([line.text], rem_patterns)
                    if clean:
                        final = apply_replace_patterns(clean, rep_patterns)[0]
                        content_lines.append(final)
                    else:
                        content_lines.append("")  # Pusta linia (usunięta przez remove)
            else:
                # Tryb Czysty - pokaż źródło
                content_lines.append(line.text)

            linenum_lines.append(str(i + 1))

        self.txt_editor.insert("1.0", "\n".join(content_lines))
        self.txt_linenums.insert("1.0", "\n".join(linenum_lines))

        if is_filtered:
            self.txt_editor.configure(state="disabled")

        self.txt_linenums.configure(state="disabled")

    def _update_preview_content(self, indices):
        rem = [p for p in self.project.patterns_subtitle if p.enabled]
        rep = [p for p in self.project.patterns_tts if p.enabled] if self.view_mode.get() == VIEW_MODE_TTS else []

        out = []
        for idx in indices:
            line = self.project.subtitle_lines[idx]

            # Zmiana: uwzględnij override w podglądzie
            if self.view_mode.get() == VIEW_MODE_TTS and line.tts_override is not None:
                out.append(f"{idx + 1:03} | {line.tts_override} [MANUAL]")
                continue

            clean = apply_remove_patterns([line.text], rem)
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
        try:
            index = self.txt_editor.index("insert")
            row = int(index.split('.')[0]) - 1
            if 0 <= row < len(self.project.subtitle_lines):
                return self.project.subtitle_lines[row]
        except:
            pass
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
        win = PatternWindow(self, title, target_list, type_key, lambda: self.refresh_ui())
        win.wait_visibility()
        win.lift()

    def open_applied_patterns_preview(self):
        if not self.project.subtitle_lines:
            return messagebox.showinfo("Info", "Brak napisów do podglądu.")
        rem = [p for p in self.project.patterns_subtitle if p.enabled]
        win = AppliedPatternsPreviewWindow(self, self.project.subtitle_lines, rem)
        win.wait_visibility()
        win.lift()

    def open_project_settings(self):
        if not self.project.project_dir:
            return messagebox.showwarning("Błąd", "Brak otwartego projektu.")
        win = SettingsWindow(self, False, mode='project')
        win.wait_visibility()
        win.lift()

    def open_global_settings(self):
        win = SettingsWindow(self, False, mode='global')
        win.wait_visibility()
        win.lift()

    def open_audio_folder(self):
        if self.project.audio_dir: os.startfile(self.project.audio_dir)

    def show_queue_window(self):
        win = GenerationQueueWindow(self)
        win.wait_visibility()
        win.lift()
        win.attributes("-topmost", True)  # Na pewno na wierzchu

    def show_about(self):
        win = AboutWindow(self, APP_VERSION)
        win.wait_visibility()
        win.lift()

    def _load_global_config(self):
        if GLOBAL_CONFIG_FILE.exists():
            try:
                with open(GLOBAL_CONFIG_FILE, "r") as f:
                    self.global_config = json.load(f)
            except:
                self.global_config = {}
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
        # Nowe okna są modalne i transient dla rodzica,
        # więc upewniamy się że rodzicem jest PatternWindow a nie main app, jeśli stamtąd wywołano
        # Ale tutaj wywołujemy z menu głównego, ok.
        win = PatternEditorWindow(self, 'remove',
                                  lambda n, o, t: self._pat_cb(n, self.project.patterns_subtitle, callback),
                                  None)
        win.wait_visibility()
        win.lift()

    def open_add_replace_pattern(self, callback):
        win = PatternEditorWindow(self, 'replace', lambda n, o, t: self._pat_cb(n, self.project.patterns_tts, callback),
                                  None)
        win.wait_visibility()
        win.lift()

    def _pat_cb(self, new_p, target_list, cb):
        target_list.append(new_p)
        self.project.save_data()
        cb()

    def save_global_config(self, data):
        self.global_config.update(data)
        with open(GLOBAL_CONFIG_FILE, "w") as f:
            json.dump(self.global_config, f, indent=2)

    def _on_editor_scroll(self, *args):
        """Synchronizuje scrollbar edytora i panel numerów linii."""
        self.txt_editor._y_scrollbar.set(*args)
        self.txt_linenums.yview_moveto(args[0])

    def _save_sync_setting(self, *args):
        """Zapisuje ustawienie synchronizacji."""
        self.save_global_config({"sync_scroll": self.sync_scroll_enabled.get()})

    def open_remove_duplicates_dialog(self):
        if not self.project.subtitle_lines:
            return messagebox.showinfo("Info", "Brak linii w projekcie.")

        seen = set()
        duplicates_count = 0

        # Symulacja
        for line in self.project.subtitle_lines:
            txt = line.text.strip()
            if txt in seen:
                duplicates_count += 1
            else:
                seen.add(txt)

        if duplicates_count == 0:
            return messagebox.showinfo("Duplikaty", "Nie znaleziono duplikatów.")

        if messagebox.askyesno("Usuń duplikaty",
                               f"Znaleziono {duplicates_count} zduplikowanych linii.\nCzy chcesz je usunąć? (Pozostanie pierwsze wystąpienie)."):

            new_lines = []
            seen_now = set()
            for line in self.project.subtitle_lines:
                txt = line.text.strip()
                if txt not in seen_now:
                    new_lines.append(line)
                    seen_now.add(txt)

            self.project.subtitle_lines = new_lines
            self.project.save_data()
            self.refresh_ui()
            self.set_status(f"Usunięto {duplicates_count} duplikatów.")

if __name__ == '__main__':
    multiprocessing.freeze_support()
    app = SubtitleStudioApp()
    app.mainloop()