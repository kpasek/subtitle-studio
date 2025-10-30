import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING
import os  # Dodano

from app.tooltip import CreateToolTip
from app.utils import is_installed

if TYPE_CHECKING:
    from app.gui import SubtitleStudioApp

DEFAULT_FILTERS = {
    "highpass": {"enabled": True, "params": "f=70"},
    "lowpass": {"enabled": True, "params": "f=14000"},
    "deesser": {"enabled": True, "params": "i=0.4:m=0.3"},
    "acompressor": {"enabled": True, "params": "threshold=-18dB:ratio=2:attack=5:release=120:makeup=2"},
    "loudnorm": {"enabled": True, "params": "I=-16:TP=-1.5:LRA=11"},
    "alimiter": {"enabled": True, "params": "limit=-1dB"}
}

FILTER_DESCRIPTIONS = {
    "highpass": "Filtr górnoprzepustowy (usuwa niskie dudnienie).",
    "lowpass": "Filtr dolnoprzepustowy (usuwa wysokie szumy).",
    "deesser": "Redukuje sybilanty ('s', 'sz', 'c').",
    "acompressor": "Kompresor (wyrównuje głośność).",
    "loudnorm": "Normalizacja głośności (standard EBU R128).",
    "alimiter": "Limiter (zapobiega przesterowaniu)."
}


class SettingsWindow(ctk.CTkToplevel):
    """
    A window for managing global application settings OR project-specific settings.
    The displayed tab depends on the 'mode' parameter.
    """

    def __init__(self, master: 'SubtitleStudioApp', torch_installed: bool, mode: str = 'global'):
        super().__init__(master)
        self.master = master
        self.torch_installed = torch_installed
        self.mode = mode  # 'global' lub 'project'
        if self.mode == 'global':
            self.title("Ustawienia Globalne")
            self.geometry("800x800")
        else:
            self.title("Ustawienia Projektu")
            self.geometry("600x300")

        self.transient(master)

        if self.mode == 'global':
            self.global_scroll_frame = ctk.CTkScrollableFrame(self)
            self.global_scroll_frame.pack(
                fill="both", expand=True, padx=10, pady=(10, 0))
            self.global_scroll_frame.grid_columnconfigure(0, weight=1)
            self._create_global_tab(self.global_scroll_frame)
        else:  # mode == 'project'
            self.project_frame = ctk.CTkFrame(self)
            self.project_frame.pack(
                fill="both", expand=True, padx=10, pady=(10, 0))
            self.project_frame.grid_columnconfigure(1, weight=1)
            self._create_project_tab(self.project_frame)
            if not self.master.current_project_path:
                messagebox.showerror(
                    "Błąd", "Brak otwartego projektu.", parent=master)
                self.after(10, self.quit)
                return

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(btn_frame, text="Anuluj",
                      command=self.destroy).pack(side="right", padx=(10, 0))
        ctk.CTkButton(btn_frame, text="Zapisz i Zamknij",
                      command=self.save_and_close).pack(side="right")

    def _create_global_tab(self, frame: ctk.CTkScrollableFrame):
        """Populates the 'Global' settings tab."""

        # Sekcja 1: Ustawienia Główne Aplikacji
        ctk.CTkLabel(frame, text="Ustawienia Główne", font=("", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 5))
        frame_main = ctk.CTkFrame(frame)
        frame_main.grid(row=1, column=0, columnspan=3,
                        sticky="ew", padx=10, pady=5)
        frame_main.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame_main, text="Startowy katalog:").grid(
            row=0, column=0, sticky="w", padx=10, pady=10)
        self.start_dir_var = tk.StringVar(
            value=self.master.global_config.get('start_directory', ''))
        entry_dir = ctk.CTkEntry(frame_main, textvariable=self.start_dir_var)
        entry_dir.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=10)
        ctk.CTkButton(frame_main, text="...", width=40, command=self.select_start_dir).grid(
            row=0, column=2, sticky="e", padx=10, pady=10)

        # *** NOWA SEKCJA: Wątki konwersji ***
        ctk.CTkLabel(frame_main, text="Procesy konwersji audio:").grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 10))

        try:
            cpu_count = os.cpu_count()
            default_workers = max(1, cpu_count // 2)
        except:
            cpu_count = "?"
            default_workers = 4

        self.conversion_workers_var = tk.StringVar(
            value=self.master.global_config.get('conversion_workers', default_workers))
        entry_workers = ctk.CTkEntry(
            frame_main, textvariable=self.conversion_workers_var)
        entry_workers.grid(row=1, column=1, sticky="ew",
                           padx=(0, 10), pady=(0, 10))
        CreateToolTip(
            entry_workers,
            f"Liczba procesów do konwersji audio (max: {cpu_count}). Więcej = szybciej, ale większe użycie CPU.",
            wraplength=300)
        # *** Koniec nowej sekcji ***

        # Sekcja 2: Modele TTS
        ctk.CTkLabel(frame, text="Modele TTS", font=("", 16, "bold")).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=10, pady=(15, 5))
        tts_tabview = ctk.CTkTabview(frame)
        tts_tabview.grid(row=3, column=0, columnspan=3,
                         sticky="ew", padx=10, pady=5)

        # Zakładka XTTS
        tab_xtts = tts_tabview.add("Local TTS (API)")  # Zmieniono nazwę
        tab_xtts.grid_columnconfigure(1, weight=1)
        # --- NOWE POLE: XTTS API URL ---
        ctk.CTkLabel(tab_xtts, text="URL serwera API:").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 5))
        self.local_api_url_var = tk.StringVar(value=self.master.global_config.get(
            'local_api_url', 'http://127.0.0.1:8001'))
        entry_xtts_url = ctk.CTkEntry(
            tab_xtts, textvariable=self.local_api_url_var)
        entry_xtts_url.grid(row=0, column=1, columnspan=2,
                            sticky="ew", padx=10, pady=(10, 5))
        CreateToolTip(
            entry_xtts_url, "Adres URL działającego serwera XTTS API.", wraplength=300)
        # --- Koniec nowego pola ---
        ctk.CTkLabel(tab_xtts, text="Ścieżka głosu XTTS (.wav):").grid(
            row=1, column=0, sticky="w", padx=10, pady=(5, 10))  # Zmieniono row na 1
        self.xtts_voice_path_var = tk.StringVar(
            value=self.master.global_config.get('xtts_voice_path', ''))
        entry_voice = ctk.CTkEntry(
            tab_xtts, textvariable=self.xtts_voice_path_var)
        entry_voice.grid(row=1, column=1, sticky="ew",
                         padx=(0, 10), pady=(5, 10))  # Zmieniono row na 1
        ctk.CTkButton(tab_xtts, text="...", width=40, command=self.select_voice_file).grid(
            row=1, column=2, sticky="e", padx=10, pady=(5, 10))  # Zmieniono row na 1
        CreateToolTip(
            entry_voice, "Ścieżka do pliku .wav używanego przez XTTS API (jeśli wymagane).", wraplength=300)
        # Usunięto wyłączanie zakładki - teraz zawsze widoczna

        # Zakładka ElevenLabs
        tab_eleven = tts_tabview.add("ElevenLabs")
        tab_eleven.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(tab_eleven, text="Klucz API:").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 5))
        self.el_api_key_var = tk.StringVar(
            value=self.master.global_config.get('elevenlabs_api_key', ''))
        ctk.CTkEntry(tab_eleven, textvariable=self.el_api_key_var, show="*").grid(
            row=0, column=1, sticky="ew", padx=10, pady=(10, 5))
        ctk.CTkLabel(tab_eleven, text="Voice ID:").grid(
            row=1, column=0, sticky="w", padx=10, pady=(5, 10))
        self.el_voice_id_var = tk.StringVar(
            value=self.master.global_config.get('elevenlabs_voice_id', ''))
        entry_el_voice = ctk.CTkEntry(
            tab_eleven, textvariable=self.el_voice_id_var)
        entry_el_voice.grid(row=1, column=1, sticky="ew",
                            padx=10, pady=(5, 10))
        CreateToolTip(
            entry_el_voice, "ID głosu z konta ElevenLabs.", wraplength=300)

        # Zakładka Google Cloud TTS
        tab_google = tts_tabview.add("Google Cloud TTS")
        tab_google.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(tab_google, text="Credentials (.json):").grid(
            row=0, column=0, sticky="w", padx=10, pady=10)
        self.gcp_creds_var = tk.StringVar(
            value=self.master.global_config.get('google_credentials_path', ''))
        entry_gcp = ctk.CTkEntry(tab_google, textvariable=self.gcp_creds_var)
        entry_gcp.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=10)
        ctk.CTkButton(tab_google, text="...", width=40, command=self.select_gcp_creds).grid(
            row=0, column=2, sticky="e", padx=10, pady=10)
        ctk.CTkLabel(tab_google, text="Nazwa głosu:").grid(
            row=1, column=0, sticky="w", padx=10, pady=(5, 10))
        self.gcp_voice_name_var = tk.StringVar(
            value=self.master.global_config.get('google_voice_name', 'pl-PL-Wavenet-B'))
        entry_gcp_voice = ctk.CTkEntry(
            tab_google, textvariable=self.gcp_voice_name_var)
        entry_gcp_voice.grid(row=1, column=1, sticky="ew",
                             padx=10, pady=(5, 10))
        CreateToolTip(entry_gcp_voice, "Np. pl-PL-Wavenet-B", wraplength=300)

        theme_frame = ctk.CTkFrame(frame)
        theme_frame.grid(row=4, column=0, columnspan=3, sticky="ew", padx=6)
        ctk.CTkLabel(theme_frame, text="Motyw aplikacji:",
                     font=("", 14, "bold")).pack(anchor="w", padx=10, pady=(5, 0))

        # 3.1. Wygląd
        ctk.CTkLabel(theme_frame, text="Wygląd (Jasny/Ciemny/System):").pack(
            anchor="w", padx=10, pady=(5, 0))
        self.appearance_mode_var = ctk.StringVar(
            value=self.master.global_config.get('appearance_mode', 'System'))
        ctk.CTkOptionMenu(theme_frame, values=["System", "Dark", "Light"],
                          variable=self.appearance_mode_var).pack(anchor="w", padx=10, pady=(0, 5))

        # 3.2. Kolor
        ctk.CTkLabel(theme_frame, text="Paleta kolorów:").pack(
            anchor="w", padx=10, pady=(5, 0))
        self.color_theme_var = ctk.StringVar(
            value=self.master.global_config.get('color_theme', 'blue'))
        ctk.CTkOptionMenu(theme_frame,
                          values=["blue", "green", "dark-blue"],
                          variable=self.color_theme_var).pack(anchor="w", padx=10, pady=(0, 10))

        # Sekcja 4: Filtry FFmpeg
        ctk.CTkLabel(frame, text="Filtry Audio (FFmpeg)", font=("", 16, "bold")).grid(
            row=5, column=0, columnspan=3, sticky="w", padx=10, pady=(20, 5))
        self.filters_frame = ctk.CTkFrame(frame)
        self.filters_frame.grid(
            row=6, column=0, columnspan=3, sticky="ew", padx=10, pady=5)
        self.filters_frame.grid_columnconfigure(1, weight=1)

        self.filter_vars = {}
        current_row = 0
        filters_config = self.master.global_config.get(
            'ffmpeg_filters', DEFAULT_FILTERS)
        for key, default_config in DEFAULT_FILTERS.items():
            current_config = filters_config.get(key, default_config)
            enabled = current_config.get("enabled", True)
            params = current_config.get("params", default_config["params"])
            params_var = tk.StringVar(value=params)
            enabled_var = tk.BooleanVar(value=enabled)
            self.filter_vars[key] = (params_var, enabled_var)
            lbl = ctk.CTkLabel(self.filters_frame, text=f"{key}:")
            lbl.grid(row=current_row, column=0, sticky="w", padx=10, pady=5)
            CreateToolTip(lbl, text=FILTER_DESCRIPTIONS.get(
                key, ""), wraplength=400)
            entry = ctk.CTkEntry(
                self.filters_frame, textvariable=params_var)
            entry.grid(row=current_row, column=1, sticky="ew", padx=10, pady=5)
            cb = ctk.CTkCheckBox(
                self.filters_frame, text="Włącz", variable=enabled_var)
            cb.grid(row=current_row, column=2, sticky="e", padx=10, pady=5)
            current_row += 1

    def _create_project_tab(self, frame: ctk.CTkFrame):
        """Populates the 'Project' settings tab."""
        ctk.CTkLabel(frame, text="Ustawienia Projektu", font=("", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 5))

        ctk.CTkLabel(frame, text="Bazowe przyspieszenie:").grid(
            row=1, column=0, sticky="w", padx=10, pady=10)
        self.base_speed_var = tk.StringVar(
            value=str(self.master.project_config.get('base_audio_speed', 1.1)))
        entry_speed = ctk.CTkEntry(frame, textvariable=self.base_speed_var)
        entry_speed.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=10)
        CreateToolTip(
            entry_speed, "Domyślna prędkość dla audio.", wraplength=300)

        ctk.CTkLabel(frame, text="Aktywny model TTS:").grid(
            row=2, column=0, sticky="w", padx=10, pady=10)
        available_models = ["XTTS", "STylish", "ElevenLabs",
                            "Google Cloud TTS"]  # Teraz wszystkie są "dostępne"
        saved_model = self.master.project_config.get(
            'active_tts_model', available_models[0])
        self.active_model_var = tk.StringVar(value=saved_model)
        model_menu = ctk.CTkOptionMenu(
            frame, variable=self.active_model_var, values=available_models)
        model_menu.grid(row=2, column=1, sticky="w", padx=10, pady=10)
        CreateToolTip(
            model_menu, "Wybierz model do generowania audio.", wraplength=300)
        ctk.CTkLabel(frame, text="Ścieżka głosu XTTS (Projekt)").grid(
            row=4, column=0, padx=10, pady=5, sticky="w")

        self.xtts_voice_project_path_var = tk.StringVar(
            value=self.master.project_config.get('xtts_voice_path', ''))

        self.ent_xtts_voice_project = ctk.CTkEntry(
            frame, width=350, textvariable=self.xtts_voice_project_path_var)
        self.ent_xtts_voice_project.grid(
            row=4, column=1, padx=(0, 10), pady=5, sticky="ew")
        self.btn_browse_xtts_voice_project = ctk.CTkButton(frame, text="...", width=30,
                                                           command=lambda: self.select_voice_file(self.xtts_voice_project_path_var))
        self.btn_browse_xtts_voice_project.grid(
            row=4, column=2, padx=10, pady=5)

        CreateToolTip(self.ent_xtts_voice_project,
                      "Opcjonalne: Nadpisz globalną ścieżkę do pliku .wav z głosem XTTS tylko dla tego projektu.")

    def select_voice_file(self, ent_path_var=None):
        """Opens dialog to select XTTS voice file."""
        path = filedialog.askopenfilename(title="Wybierz plik głosu .wav", filetypes=[
            ("Wave", "*.wav")], initialdir=self._get_initial_dir(), parent=self)
        if path:
            if ent_path_var is None:
                ent_path_var = self.xtts_voice_path_var
            ent_path_var.set(path)

    def select_gcp_creds(self):
        """Opens dialog to select GCP credentials file."""
        path = filedialog.askopenfilename(title="Wybierz credentials .json", filetypes=[
            ("JSON", "*.json")], initialdir=self._get_initial_dir(), parent=self)
        if path:
            self.gcp_creds_var.set(path)

    def select_start_dir(self):
        """Opens dialog to select default start directory."""
        path = filedialog.askdirectory(
            title="Wybierz startowy katalog", initialdir=self._get_initial_dir(), parent=self)
        if path:
            self.start_dir_var.set(path)

    def _get_initial_dir(self) -> str | None:
        """Gets the initial directory for file dialogs."""
        return self.master.global_config.get('start_directory')

    def save_and_close(self):
        """Saves settings based on the current mode and closes."""
        if self.mode == 'global':
            self._save_global_settings()
        elif self.mode == 'project':
            self._save_project_settings()
        self.destroy()

    def _save_global_settings(self):
        """Saves the global settings."""
        try:
            old_voice_path = self.master.global_config.get('xtts_voice_path')
            new_voice_path = self.xtts_voice_path_var.get()

            filters_data = {key: {"enabled": en_var.get(), "params": par_var.get()}
                            for key, (par_var, en_var) in self.filter_vars.items()}

            # *** ZMIANA: Walidacja i zapis conversion_workers ***
            try:
                cpu_count = os.cpu_count()
                workers = int(self.conversion_workers_var.get())
                # Prosta walidacja - nie mniej niż 1, nie więcej niż (CPU * 2)
                workers = max(
                    1, min(workers, cpu_count * 2 if cpu_count else 32))
            except ValueError:
                workers = max(1, os.cpu_count() // 2 if os.cpu_count() else 4)
            except:  # Na wypadek gdyby os.cpu_count() zawiodło
                workers = 4

            global_data = {
                'start_directory': self.start_dir_var.get(),
                'conversion_workers': workers,  # Zapisz liczbę wątków
                'local_api_url': self.local_api_url_var.get(),  # Zapisz URL API
                'xtts_voice_path': new_voice_path,
                'elevenlabs_api_key': self.el_api_key_var.get(),
                'elevenlabs_voice_id': self.el_voice_id_var.get(),
                'google_credentials_path': self.gcp_creds_var.get(),
                'google_voice_name': self.gcp_voice_name_var.get(),
                'ffmpeg_filters': filters_data,
                'appearance_mode': self.appearance_mode_var.get(),
                'color_theme': self.color_theme_var.get()
            }
            # *** Koniec zmiany ***

            self.master.save_global_config(global_data)
            self.master.apply_theme_settings()

            # Reset cached model if voice/API keys changed
            # Prościej: zawsze resetuj przy zapisie ustawień globalnych
            self.master.tts_model = None
            print("Wyczyszczono cache modelu TTS z powodu zapisu ustawień globalnych.")

        except Exception as e:
            messagebox.showerror(
                "Błąd zapisu globalnego", f"Błąd:\n{e}", parent=self)

    def _save_project_settings(self):
        """Saves the project-specific settings."""
        if not self.master.current_project_path:
            return  # Sanity check

        try:
            speed_str = self.base_speed_var.get().replace(',', '.')
            speed = float(speed_str)
            # set_project_config zapisuje i oznacza zmiany
            self.master.set_project_config('base_audio_speed', speed)
            self.master.set_project_config(
                'active_tts_model', self.active_model_var.get())
            self.master.set_project_config(
                'xtts_voice_path', self.xtts_voice_project_path_var.get())
        except ValueError:
            messagebox.showerror(
                "Błędna wartość", "Przyspieszenie musi być liczbą.", parent=self)
        except Exception as e:
            messagebox.showerror(
                "Błąd zapisu projektu", f"Błąd:\n{e}", parent=self)
