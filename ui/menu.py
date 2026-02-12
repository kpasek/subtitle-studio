import tkinter as tk
from tkinter import messagebox
from app.project import (create_new_project, import_old_project, open_project, save_project, save_project_as, close_project, 
                         open_recent_projects_window, add_new_subtitles, change_subtitle_file, download_clean, download_replace,
                         delete_all_converted_audio)
from app.generation import enqueue_generate_all, enqueue_convert_all
from app.patterns import open_pattern_manager
from app.ui_helpers import open_shortcuts_window, show_about_window
from audio.deleter import AudioDeleterWindow
from ui.verification_window import VerificationWindow
from ui.pattern_io import PatternIOWindow
from ui.game_reader_export import GameReaderExportWindow
from ui.ai_task_manager import AITaskManagerWindow
from ui.ai_runner import AITaskRunnerWindow
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

        # --- Edycja ---
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Przywróć wartość", command=lambda: self._invoke_panel("restore_selected_values"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Oznacz jako Gotowe", command=lambda: self._invoke_panel("set_selected_status", "DONE"))
        edit_menu.add_command(label="Oznacz jako Błędne", command=lambda: self._invoke_panel("set_selected_status", "ERROR"))
        edit_menu.add_command(label="Wyczyść flagi", command=lambda: self._invoke_panel("set_selected_status", None))
        menubar.add_cascade(label="Edycja", menu=edit_menu)

        # --- Dialogi ---
        gen_menu = tk.Menu(menubar, tearoff=0)
        gen_menu.add_command(label="Dodaj nowe napisy", command=lambda: add_new_subtitles(self.app))
        gen_menu.add_command(label="Zmień plik z danymi", command=lambda: change_subtitle_file(self.app))
        gen_menu.add_separator()
        gen_menu.add_command(label="Generuj dialogi", command=lambda: enqueue_generate_all(self.app), accelerator="Ctrl+Shift+G")
        gen_menu.add_command(label="Konwertuj audio", command=lambda: enqueue_convert_all(self.app), accelerator="Ctrl+Shift+R")
        gen_menu.add_command(label="Weryfikacja", command=lambda: VerificationWindow(self.app), accelerator="Ctrl+Shift+Y")
        gen_menu.add_command(label="Zatwierdź zamiany", command=lambda: VerificationWindow(self.app))
        gen_menu.add_separator()
        gen_menu.add_command(label="Usuń przekonwertowane pliki", command=lambda: delete_all_converted_audio(self.app))
        menubar.add_cascade(label="Dialogi", menu=gen_menu)

        # --- SI / Ollama ---
        ai_menu = tk.Menu(menubar, tearoff=0)
        ai_menu.add_command(label="Menedżer Zadań SI", command=lambda: AITaskManagerWindow(self.app))
        ai_menu.add_command(label="Uruchom zadania SI", command=lambda: self._run_ai_global(), accelerator="Ctrl+Shift+A")
        menubar.add_cascade(label="Zadania SI", menu=ai_menu)
        
        # --- Wzorce ---
        patterns_menu = tk.Menu(menubar, tearoff=0)

        patterns_menu.add_command(label="Menedżer wzorców", command=lambda: open_pattern_manager(self.app), accelerator="Ctrl+R")
        patterns_menu.add_command(label="Importuj wzorce z CSV", command=lambda: self._open_pattern_io("Import"))
        patterns_menu.add_command(label="Eksportuj wzorce do CSV", command=lambda: self._open_pattern_io("Eksport"))
        patterns_menu.add_separator()
        patterns_menu.add_command(label="Usuwanie dialogów", command=lambda: self._run_audio_deleter())
        menubar.add_cascade(label="Wzorce", menu=patterns_menu)
                
        export_menu = tk.Menu(menubar, tearoff=0)
        export_menu.add_command(label="Eksportuj napisy", command=lambda: download_clean(self.app))
        export_menu.add_command(label="Eksportuj napisy TTS", command=lambda: download_replace(self.app))
        export_menu.add_command(label="Generuj preset", command=lambda: self._open_game_reader_export())
        menubar.add_cascade(label="Eksport", menu=export_menu)

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
            messagebox.showwarning("Brak danych", "Najpierw przetwórz.", parent=self.app)
            return
        if not self.app.audio_dir:
            messagebox.showwarning("Brak katalogu", "Ustaw katalog audio.", parent=self.app)
            return
        
        win = AudioDeleterWindow(self.app, self.app.lines, str(self.app.audio_dir))
        win.wait_visibility()
        win.grab_set()

    def _run_ai_global(self):
        if not self.app.lines:
             messagebox.showwarning("Brak danych", "Brak wierszy do przetworzenia.", parent=self.app)
             return
        
        # Select all lines
        all_lines = self.app.lines
        AITaskRunnerWindow(self.app, all_lines, is_global=True)

    def _invoke_panel(self, method_name, *args):
        if hasattr(self.app, 'subtitle_panel') and hasattr(self.app.subtitle_panel, method_name):
            method = getattr(self.app.subtitle_panel, method_name)
            method(*args)
        else:
            print(f"Warning: Cannot invoke {method_name} on subtitle_panel")

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

        self.export_window = GameReaderExportWindow(self.app)

