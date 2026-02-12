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
    "highpass": {"enabled": False, "params": "f=70"},
    "lowpass": {"enabled": False, "params": "f=14000"},
    "deesser": {"enabled": False, "params": "i=0.4:m=0.3"},
    "acompressor": {"enabled": False, "params": "threshold=-18dB:ratio=2:attack=5:release=120:makeup=2"},
    "loudnorm": {"enabled": False, "params": "I=-16:TP=-1.5:LRA=11"},
    "alimiter": {"enabled": False, "params": "limit=-1dB"}
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
        """Populates the 'Global' settings tab using sub-tabs."""
        
        # Create main Tabview
        self.main_tabs = ctk.CTkTabview(frame)
        self.main_tabs.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Define tabs
        tab_general = self.main_tabs.add("Ogólne")
        tab_tts = self.main_tabs.add("TTS")
        tab_ai = self.main_tabs.add("SI")
        tab_filters = self.main_tabs.add("Filtry Audio")
        tab_theme = self.main_tabs.add("Wygląd")
        
        # --- TAB: Ogólne ---
        tab_general.grid_columnconfigure(1, weight=1)
        
        # Start Directory
        ctk.CTkLabel(tab_general, text="Startowy katalog:").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        self.start_dir_var = tk.StringVar(value=self.master.global_config.get('start_directory', ''))
        ctk.CTkEntry(tab_general, textvariable=self.start_dir_var).grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=10)
        ctk.CTkButton(tab_general, text="...", width=40, command=self.select_start_dir).grid(row=0, column=2, sticky="e", padx=10, pady=10)

        # Workers
        ctk.CTkLabel(tab_general, text="Procesy weryfikacji:").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        try:
            cpu_count = os.cpu_count()
            default_workers = max(1, cpu_count // 2)
        except:
            cpu_count = "?"
            default_workers = 4
        self.verification_workers_var = tk.StringVar(value=self.master.global_config.get('verification_workers', self.master.global_config.get('conversion_workers', default_workers)))
        entry_workers = ctk.CTkEntry(tab_general, textvariable=self.verification_workers_var)
        entry_workers.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=10)
        CreateToolTip(entry_workers, f"Liczba procesów do weryfikacji audio (max: {cpu_count}).", wraplength=300)

        # Audio Format
        ctk.CTkLabel(tab_general, text="Format wyjściowy audio:").grid(row=2, column=0, sticky="w", padx=10, pady=10)
        self.audio_format_var = tk.StringVar(value=self.master.global_config.get('audio_output_format', 'mp3'))
        ctk.CTkOptionMenu(tab_general, variable=self.audio_format_var, values=["ogg", "mp3"]).grid(row=2, column=1, sticky="w", padx=(0, 10), pady=10)
        ctk.CTkLabel(tab_general, text="(Format plików w folderze /ready)").grid(row=2, column=2, sticky="w", padx=5)

        # --- TAB: TTS ---
        tts_inner_tabs = ctk.CTkTabview(tab_tts)
        tts_inner_tabs.pack(fill="both", expand=True, padx=5, pady=5)
        
        # XTTS
        t_xtts = tts_inner_tabs.add("Local TTS (API)")
        t_xtts.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(t_xtts, text="URL serwera API:").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        self.local_api_url_var = tk.StringVar(value=self.master.global_config.get('local_api_url', 'http://127.0.0.1:8001'))
        ctk.CTkEntry(t_xtts, textvariable=self.local_api_url_var).grid(row=0, column=1, columnspan=2, sticky="ew", padx=10, pady=10)
        
        ctk.CTkLabel(t_xtts, text="Ścieżka głosu XTTS (.wav):").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        self.xtts_voice_path_var = tk.StringVar(value=self.master.global_config.get('xtts_voice_path', ''))
        ctk.CTkEntry(t_xtts, textvariable=self.xtts_voice_path_var).grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=10)
        ctk.CTkButton(t_xtts, text="...", width=40, command=self.select_voice_file).grid(row=1, column=2, sticky="e", padx=10, pady=10)

        # ElevenLabs
        t_eleven = tts_inner_tabs.add("ElevenLabs")
        t_eleven.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(t_eleven, text="Klucz API:").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        self.el_api_key_var = tk.StringVar(value=self.master.global_config.get('elevenlabs_api_key', ''))
        ctk.CTkEntry(t_eleven, textvariable=self.el_api_key_var, show="*").grid(row=0, column=1, sticky="ew", padx=10, pady=10)
        
        ctk.CTkLabel(t_eleven, text="Voice ID:").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        self.el_voice_id_var = tk.StringVar(value=self.master.global_config.get('elevenlabs_voice_id', ''))
        ctk.CTkEntry(t_eleven, textvariable=self.el_voice_id_var).grid(row=1, column=1, sticky="ew", padx=10, pady=10)

        # Google
        t_google = tts_inner_tabs.add("Google Cloud TTS")
        t_google.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(t_google, text="Credentials (.json):").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        self.gcp_creds_var = tk.StringVar(value=self.master.global_config.get('google_credentials_path', ''))
        ctk.CTkEntry(t_google, textvariable=self.gcp_creds_var).grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=10)
        ctk.CTkButton(t_google, text="...", width=40, command=self.select_gcp_creds).grid(row=0, column=2, sticky="e", padx=10, pady=10)
        
        ctk.CTkLabel(t_google, text="Nazwa głosu:").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        self.gcp_voice_name_var = tk.StringVar(value=self.master.global_config.get('google_voice_name', 'pl-PL-Wavenet-B'))
        ctk.CTkEntry(t_google, textvariable=self.gcp_voice_name_var).grid(row=1, column=1, sticky="ew", padx=10, pady=10)

        # Piper
        t_piper = tts_inner_tabs.add("Piper")
        t_piper.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(t_piper, text="Ścieżka modelu Piper (.onnx):").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        self.piper_model_path_var = tk.StringVar(value=self.master.global_config.get('piper_model_path', ''))
        ctk.CTkEntry(t_piper, textvariable=self.piper_model_path_var).grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=10)
        ctk.CTkButton(t_piper, text="...", width=40, command=self.select_model_file).grid(row=0, column=2, sticky="e", padx=10, pady=10)

        # --- TAB: SI ---
        tab_ai.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(tab_ai, text="Url serwera Ollama:").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        self.ollama_url_var = tk.StringVar(value=self.master.global_config.get('ollama_url', 'http://localhost:11434'))
        ctk.CTkEntry(tab_ai, textvariable=self.ollama_url_var).grid(row=0, column=1, sticky="ew", padx=10, pady=10)
        CreateToolTip(tab_ai, "Adres API Ollama (domyślnie http://localhost:11434)")
        
        ctk.CTkLabel(tab_ai, text="Model Ollama:").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        self.ollama_model_var = tk.StringVar(value=self.master.global_config.get('ollama_model', 'gemma2:2b'))
        ctk.CTkEntry(tab_ai, textvariable=self.ollama_model_var).grid(row=1, column=1, sticky="ew", padx=10, pady=10)
        CreateToolTip(tab_ai, "Nazwa modelu do użycia (musi być zainstalowana w Ollama)")

        # --- TAB: Filtry Audio ---
        tab_filters.grid_columnconfigure(1, weight=1)
        self.filter_vars = {}
        filters_config = self.master.global_config.get('ffmpeg_filters', DEFAULT_FILTERS)
        current_row=0
        for key, default_config in DEFAULT_FILTERS.items():
            current_config = filters_config.get(key, default_config)
            enabled = current_config.get("enabled", True)
            params = current_config.get("params", default_config["params"])
            
            p_var = tk.StringVar(value=params)
            e_var = tk.BooleanVar(value=enabled)
            self.filter_vars[key] = (p_var, e_var)
            
            lbl = ctk.CTkLabel(tab_filters, text=f"{key}:")
            lbl.grid(row=current_row, column=0, sticky="w", padx=10, pady=5)
            CreateToolTip(lbl, text=FILTER_DESCRIPTIONS.get(key, ""), wraplength=400)
            
            ctk.CTkEntry(tab_filters, textvariable=p_var).grid(row=current_row, column=1, sticky="ew", padx=10, pady=5)
            ctk.CTkCheckBox(tab_filters, text="Włącz", variable=e_var).grid(row=current_row, column=2, sticky="e", padx=10, pady=5)
            current_row+=1

        # --- TAB: Wygląd ---
        # Appearance Mode
        ctk.CTkLabel(tab_theme, text="Wygląd (Jasny/Ciemny/System):").pack(anchor="w", padx=10, pady=(10, 0))
        self.appearance_mode_var = ctk.StringVar(value=self.master.global_config.get('appearance_mode', 'System'))
        ctk.CTkOptionMenu(tab_theme, values=["System", "Dark", "Light"], variable=self.appearance_mode_var).pack(anchor="w", padx=10, pady=(5, 10))

        # Color Theme
        ctk.CTkLabel(tab_theme, text="Paleta kolorów:").pack(anchor="w", padx=10, pady=(10, 0))
        self.color_theme_var = ctk.StringVar(value=self.master.global_config.get('color_theme', 'blue'))
        ctk.CTkOptionMenu(tab_theme, values=["blue", "green", "dark-blue"], variable=self.color_theme_var).pack(anchor="w", padx=10, pady=(5, 10))

    def _create_project_tab(self, frame: ctk.CTkFrame):
        """Populates the 'Project' settings tab."""
        ctk.CTkLabel(frame, text="Ustawienia Projektu", font=("", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 5))

        ctk.CTkLabel(frame, text="Aktywny model TTS:").grid(
            row=2, column=0, sticky="w", padx=10, pady=10)
        available_models = ["XTTS", "STylish", "ElevenLabs",
                            "Google Cloud TTS", "Piper"]
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
                                                           command=lambda: self.select_voice_file(
                                                               self.xtts_voice_project_path_var))
        self.btn_browse_xtts_voice_project.grid(
            row=4, column=2, padx=10, pady=5)

        CreateToolTip(self.ent_xtts_voice_project,
                      "Opcjonalne: Nadpisz globalną ścieżkę do pliku .wav z głosem XTTS tylko dla tego projektu.")


        ctk.CTkLabel(frame, text="Ścieżka modelu Piper (Projekt)").grid(
            row=5, column=0, padx=10, pady=5, sticky="w")

        self.piper_model_project_path_var = tk.StringVar(
            value=self.master.project_config.get('piper_model_path', ''))

        self.ent_piper_model_project = ctk.CTkEntry(
            frame, width=350, textvariable=self.piper_model_project_path_var)
        self.ent_piper_model_project.grid(
            row=5, column=1, padx=(0, 10), pady=5, sticky="ew")
        self.btn_browse_piper_model_project = ctk.CTkButton(frame, text="...", width=30,
                                                           command=lambda: self.select_model_file(
                                                               self.piper_model_project_path_var))
        self.btn_browse_piper_model_project.grid(
            row=5, column=2, padx=10, pady=5)

        CreateToolTip(self.ent_piper_model_project,
                      "Opcjonalne: Nadpisz globalną ścieżkę do pliku .onnx z modelem Piper tylko dla tego projektu.")


    def select_voice_file(self, ent_path_var=None):
        """Opens dialog to select XTTS voice file."""
        path = filedialog.askopenfilename(title="Wybierz plik głosu .wav", filetypes=[
            ("Wave", "*.wav")], initialdir=self._get_initial_dir(), parent=self)
        if path:
            if ent_path_var is None:
                ent_path_var = self.xtts_voice_path_var
            ent_path_var.set(path)

    def select_model_file(self, ent_path_var=None):
        """Opens dialog to select XTTS voice file."""
        path = filedialog.askopenfilename(title="Wybierz plik głosu .onnx", filetypes=[
            ("Model", "*.onnx")], initialdir=self._get_initial_dir(), parent=self)
        if path:
            if ent_path_var is None:
                ent_path_var = self.piper_model_path_var
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

            try:
                cpu_count = os.cpu_count()
                workers = int(self.verification_workers_var.get())
                # Prosta walidacja - nie mniej niż 1, nie więcej niż (CPU * 2)
                workers = max(
                    1, min(workers, cpu_count * 2 if cpu_count else 32))
            except ValueError:
                workers = max(1, os.cpu_count() // 2 if os.cpu_count() else 4)
            except:  # Na wypadek gdyby os.cpu_count() zawiodło
                workers = 4

            global_data = {
                'start_directory': self.start_dir_var.get(),
                'verification_workers': workers,
                'local_api_url': self.local_api_url_var.get(),
                'ollama_url': self.ollama_url_var.get(),
                'ollama_model': self.ollama_model_var.get(),
                'audio_output_format': self.audio_format_var.get(),
                'xtts_voice_path': new_voice_path,

                'elevenlabs_api_key': self.el_api_key_var.get(),
                'elevenlabs_voice_id': self.el_voice_id_var.get(),
                'google_credentials_path': self.gcp_creds_var.get(),
                'google_voice_name': self.gcp_voice_name_var.get(),
                'piper_model_path': self.piper_model_path_var.get().strip(),
                'ffmpeg_filters': filters_data,
                'appearance_mode': self.appearance_mode_var.get(),
                'color_theme': self.color_theme_var.get()
            }

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
            self.master.set_project_config(
                'active_tts_model', self.active_model_var.get())
            self.master.set_project_config(
                'xtts_voice_path', self.xtts_voice_project_path_var.get())
            self.master.set_project_config(
                'piper_model_path', self.piper_model_project_path_var.get().strip())
        except ValueError:
            messagebox.showerror(
                "Błędna wartość", "Przyspieszenie musi być liczbą.", parent=self)
        except Exception as e:
            messagebox.showerror(
                "Błąd zapisu projektu", f"Błąd:\n{e}", parent=self)
