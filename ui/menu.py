import tkinter as tk


class AppMenu:
    """Zarządza paskiem menu aplikacji."""

    def __init__(self, app):
        self.app = app

    def create(self):
        menubar = tk.Menu(self.app)

        # --- Projekt ---
        config_menu = tk.Menu(menubar, tearoff=0)
        config_menu.add_command(label="Otwórz projekt (.json)", command=self.app.open_project)
        config_menu.add_command(label="Otwórz ostatni...", command=self.app.open_recent_projects_window,
                                accelerator="Ctrl+E")
        config_menu.add_command(label="Zapisz projekt", command=self.app.save_project, accelerator="Ctrl+S")
        config_menu.add_command(label="Zapisz jako", command=self.app.save_project_as)
        config_menu.add_separator()
        config_menu.add_command(label="Zamknij projekt", command=self.app.close_project)
        config_menu.add_separator()
        config_menu.add_command(label="Zamknij", command=self.app.on_close)
        menubar.add_cascade(label="Projekt", menu=config_menu)

        # --- Dialogi ---
        gen_menu = tk.Menu(menubar, tearoff=0)
        gen_menu.add_command(label="Wczytaj napisy", command=self.app.load_file)
        gen_menu.add_command(label="Wybierz katalog audio", command=self.app.choose_audio_dir)
        gen_menu.add_separator()
        gen_menu.add_command(label="Pokaż kolejkę zadań", command=self.app.show_generation_queue)
        gen_menu.add_command(label="Generuj dialogi", command=self.app.enqueue_generate_all, accelerator="Ctrl+Shift+G")
        gen_menu.add_command(label="Konwertuj audio", command=self.app.enqueue_convert_all, accelerator="Ctrl+Shift+R")
        gen_menu.add_separator()
        gen_menu.add_command(label="Dopasuj identyfikatory audio", command=self.app.open_audio_rename_window)
        gen_menu.add_command(label="Usuń przekonwertowane pliki", command=self.app.delete_all_converted_audio)
        gen_menu.add_separator()
        gen_menu.add_command(label="Pobierz napisy", command=self.app.download_clean)
        gen_menu.add_command(label="Pobierz napisy TTS", command=self.app.download_replace)
        gen_menu.add_command(label="Generuj preset", command=self.app.generate_game_reader_preset)
        menubar.add_cascade(label="Dialogi", menu=gen_menu)

        # --- Wzorce ---
        patterns_menu = tk.Menu(menubar, tearoff=0)
        patterns_menu.add_command(label="Menedżer wzorców", command=self.app.open_pattern_manager, accelerator="Ctrl+R")
        patterns_menu.add_command(label="Importuj wzorce z CSV", command=self.app.import_patterns_from_csv)
        patterns_menu.add_command(label="Eksportuj wzorce do CSV", command=self.app.export_patterns_to_csv)
        patterns_menu.add_separator()
        patterns_menu.add_command(label="Usuwanie dialogów", command=self.app.open_audio_deleter)
        menubar.add_cascade(label="Wzorce", menu=patterns_menu)

        # --- Ustawienia ---
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Ustawienia aplikacji", command=self.app.open_global_settings)
        settings_menu.add_command(label="Ustawienia projektu", command=self.app.open_project_settings)
        menubar.add_cascade(label="Ustawienia", menu=settings_menu)

        # --- Pomoc ---
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Skróty klawiszowe", command=self.app.open_shortcuts_window)
        help_menu.add_command(label="O programie", command=self.app.show_about_window)
        menubar.add_cascade(label="Pomoc", menu=help_menu)

        self.app.config(menu=menubar)