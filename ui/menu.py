import tkinter as tk
from tkinter import messagebox
from app.project import (create_new_project, import_old_project, open_project, save_project, save_project_as, close_project, 
                         open_recent_projects_window, save_global_config,
                         add_new_subtitles, change_subtitle_file, download_clean, download_replace,
                         delete_all_converted_audio)
from app.generation import enqueue_generate_all, enqueue_convert_all, show_generation_queue
from app.patterns import open_pattern_manager
from app.ui_helpers import open_shortcuts_window, show_about_window
from audio.deleter import AudioDeleterWindow
from ui.verification_window import VerificationWindow
from ui.pattern_io import PatternIOWindow
from ui.game_reader_export import GameReaderExportWindow
from audio.generation_queue import GenerationQueueWindow
from app.settings import SettingsWindow


class AppMenu:
    """Zarządza paskiem menu aplikacji."""

    def __init__(self, app):
        self.app = app

    def create(self):
        menubar = tk.Menu(self.app)

        # --- Projekt ---
        config_menu = tk.Menu(menubar, tearoff=0)
        config_menu.add_command(label="Nowy projekt", command=lambda: create_new_project(self.app))
        config_menu.add_command(label="Importuj projekt (starsza wersja)", command=lambda: import_old_project(self.app))
        config_menu.add_separator()
        config_menu.add_command(label="Otwórz projekt (.json)", command=lambda: open_project(self.app))
        config_menu.add_command(label="Otwórz ostatni...", command=lambda: open_recent_projects_window(self.app),
                                accelerator="Ctrl+E")
        config_menu.add_command(label="Zapisz projekt", command=lambda: save_project(self.app), accelerator="Ctrl+S")
        config_menu.add_command(label="Zapisz jako", command=lambda: save_project_as(self.app))
        config_menu.add_separator()
        config_menu.add_command(label="Zamknij projekt", command=lambda: close_project(self.app))
        config_menu.add_separator()
        config_menu.add_command(label="Zamknij", command=self.app.on_close)
        menubar.add_cascade(label="Projekt", menu=config_menu)

        # --- Dialogi ---
        gen_menu = tk.Menu(menubar, tearoff=0)
        gen_menu.add_command(label="Dodaj nowe napisy", command=lambda: add_new_subtitles(self.app))
        gen_menu.add_command(label="Zmień plik z danymi", command=lambda: change_subtitle_file(self.app))
        gen_menu.add_separator()
        gen_menu.add_command(label="Generuj dialogi", command=lambda: enqueue_generate_all(self.app), accelerator="Ctrl+Shift+G")
        gen_menu.add_command(label="Konwertuj audio", command=lambda: enqueue_convert_all(self.app), accelerator="Ctrl+Shift+R")
        gen_menu.add_command(label="Weryfikacja", command=lambda: VerificationWindow(self.app), accelerator="Ctrl+Shift+Y")
        gen_menu.add_separator()
        gen_menu.add_command(label="Usuń przekonwertowane pliki", command=lambda: delete_all_converted_audio(self.app))
        gen_menu.add_separator()
        gen_menu.add_command(label="Pobierz napisy", command=lambda: download_clean(self.app))
        gen_menu.add_command(label="Pobierz napisy TTS", command=lambda: download_replace(self.app))
        gen_menu.add_command(label="Generuj preset", command=lambda: self._open_game_reader_export())
        
        # --- Weryfikacja: otwiera dedykowane okno sterujące weryfikacją ---
        menubar.add_cascade(label="Dialogi", menu=gen_menu)


        # --- Wzorce ---
        patterns_menu = tk.Menu(menubar, tearoff=0)
        patterns_menu.add_command(label="Menedżer wzorców", command=lambda: open_pattern_manager(self.app), accelerator="Ctrl+R")
        patterns_menu.add_command(label="Importuj wzorce z CSV", command=lambda: self._open_pattern_io("Import"))
        patterns_menu.add_command(label="Eksportuj wzorce do CSV", command=lambda: self._open_pattern_io("Eksport"))
        patterns_menu.add_separator()
        patterns_menu.add_command(label="Usuwanie dialogów", command=lambda: self._run_audio_deleter())
        menubar.add_cascade(label="Wzorce", menu=patterns_menu)

        # --- Ustawienia ---
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Ustawienia aplikacji", command=lambda: SettingsWindow(self.app, self.app.torch_installed, mode='global'))
        settings_menu.add_command(label="Ustawienia projektu", command=lambda: self._open_project_settings())
        menubar.add_cascade(label="Ustawienia", menu=settings_menu)

        # --- Pomoc ---
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Skróty klawiszowe", command=lambda: open_shortcuts_window(self.app))
        help_menu.add_command(label="O programie", command=lambda: show_about_window(self.app))
        menubar.add_cascade(label="Pomoc", menu=help_menu)

        self.app.config(menu=menubar)

    def _open_pattern_io(self, tab):
        win = PatternIOWindow(self.app)
        win.tabview.set(tab)

    def _run_audio_deleter(self):
        if not self.app.lines:
            return messagebox.showwarning("Brak danych", "Najpierw przetwórz.", parent=self.app)
        if not self.app.audio_dir: 
            return messagebox.showwarning("Brak katalogu", "Ustaw katalog audio.", parent=self.app)

        win = AudioDeleterWindow(self.app, self.app.lines, str(self.app.audio_dir))
        win.wait_visibility()
        win.grab_set()

    def _open_project_settings(self):
        if not self.app.current_project_path: 
            return messagebox.showwarning("Brak projektu", "Zapisz projekt.", parent=self.app)
        SettingsWindow(self.app, self.app.torch_installed, mode='project')

    def _open_game_reader_export(self):
        if not self.app.lines:
            messagebox.showwarning('Brak danych', 'Brak przetworzonych napisów do wyeksportowania.', parent=self.app)
            return

        if not self.app.audio_dir:
            messagebox.showwarning('Brak audio', 'Nie wybrano katalogu audio w projekcie.', parent=self.app)
            return

        GameReaderExportWindow(self.app)


        
    
    # def open_verification_window(self):  <-- Usunięte, teraz jest w studio.py
