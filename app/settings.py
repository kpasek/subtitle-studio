import customtkinter as ctk
import json
from pathlib import Path

# Domyślne wartości
DEFAULT_CONFIG = {
    "appearance_mode": "System",
    "color_theme": "blue",
    "conversion_workers": 4,
    "base_audio_speed": 1.1,
    "active_tts_model": "XTTS",  # Domyślny fallback
    "default_tts_model": "XTTS",  # Nowe ustawienie globalne
    "ffmpeg_filters": {
        "af": "silenceremove=stop_periods=-1:stop_duration=1:stop_threshold=-60dB"
    },
    "recent_projects": []
}


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, torch_available: bool, mode: str = 'global'):
        super().__init__(master)
        self.title("Ustawienia " + ("Globalne" if mode == 'global' else "Projektu"))
        self.geometry("500x600")
        self.transient(master)
        self.lift()
        self.app = master
        self.mode = mode
        self.torch_available = torch_available

        # Wczytaj konfig w zależności od trybu
        if mode == 'global':
            self.current_config = self.app.global_config.copy()
        else:
            self.current_config = self.app.project.get_all_settings()  # Musi zwrócić dict
            # Fallback do globalnych jeśli projekt nie ma ustawień
            for k, v in self.app.global_config.items():
                if k not in self.current_config:
                    self.current_config[k] = v

        self._create_widgets()

    def _create_widgets(self):
        # Scrollable container
        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # --- Wygląd (Tylko globalne) ---
        if self.mode == 'global':
            ctk.CTkLabel(scroll, text="Wygląd Aplikacji", font=("", 14, "bold")).pack(pady=5, anchor="w")

            self.var_theme = ctk.StringVar(value=self.current_config.get("appearance_mode", "System"))
            ctk.CTkOptionMenu(scroll, variable=self.var_theme, values=["System", "Dark", "Light"]).pack(pady=5)

            self.var_color = ctk.StringVar(value=self.current_config.get("color_theme", "blue"))
            ctk.CTkOptionMenu(scroll, variable=self.var_color, values=["blue", "green", "dark-blue"]).pack(pady=5)

            ctk.CTkLabel(scroll, text="Domyślny Model TTS", font=("", 14, "bold")).pack(pady=(15, 5), anchor="w")
            self.var_default_model = ctk.StringVar(value=self.current_config.get("default_tts_model", "XTTS"))
            models = ["XTTS", "ElevenLabs", "Google Cloud TTS", "STylish"]
            ctk.CTkOptionMenu(scroll, variable=self.var_default_model, values=models).pack(pady=5)

        # --- Audio & TTS (Projekt lub override) ---
        title = "Ustawienia Audio" if self.mode == 'project' else "Domyślne Ustawienia Audio"
        ctk.CTkLabel(scroll, text=title, font=("", 14, "bold")).pack(pady=(15, 5), anchor="w")

        if self.mode == 'project':
            ctk.CTkLabel(scroll, text="Model TTS dla tego projektu:").pack(anchor="w")
            self.var_proj_model = ctk.StringVar(value=self.current_config.get("active_tts_model", "XTTS"))
            models = ["XTTS", "ElevenLabs", "Google Cloud TTS", "STylish"]
            ctk.CTkOptionMenu(scroll, variable=self.var_proj_model, values=models).pack(pady=5)

        ctk.CTkLabel(scroll, text="Szybkość bazowa (Audio Convert):").pack(anchor="w")
        self.var_speed = ctk.StringVar(value=str(self.current_config.get("base_audio_speed", 1.1)))
        ctk.CTkEntry(scroll, textvariable=self.var_speed).pack(pady=5)

        ctk.CTkLabel(scroll, text="Wątki konwersji (CPU):").pack(anchor="w")
        self.var_workers = ctk.StringVar(value=str(self.current_config.get("conversion_workers", 4)))
        ctk.CTkEntry(scroll, textvariable=self.var_workers).pack(pady=5)

        # --- Filtry FFmpeg ---
        ctk.CTkLabel(scroll, text="Filtry FFmpeg (JSON):").pack(anchor="w", pady=(10, 0))
        self.txt_filters = ctk.CTkTextbox(scroll, height=100)
        self.txt_filters.pack(fill="x", pady=5)

        filters_str = json.dumps(self.current_config.get("ffmpeg_filters", {}), indent=2)
        self.txt_filters.insert("1.0", filters_str)

        # Buttons
        btn_frame = ctk.CTkFrame(self)
        btn_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(btn_frame, text="Anuluj", command=self.destroy, fg_color="gray").pack(side="left", expand=True,
                                                                                            padx=5)
        ctk.CTkButton(btn_frame, text="Zapisz", command=self.save, fg_color="green").pack(side="right", expand=True,
                                                                                          padx=5)

    def save(self):
        try:
            new_filters = json.loads(self.txt_filters.get("1.0", "end"))
        except json.JSONDecodeError:
            return  # lub messagebox z błędem

        new_data = {
            "base_audio_speed": float(self.var_speed.get()),
            "conversion_workers": int(self.var_workers.get()),
            "ffmpeg_filters": new_filters
        }

        if self.mode == 'global':
            new_data["appearance_mode"] = self.var_theme.get()
            new_data["color_theme"] = self.var_color.get()
            new_data["default_tts_model"] = self.var_default_model.get()
            self.app.save_global_config(new_data)
            # Ważne: Wywołanie metody w GUI do odświeżenia motywu
            if hasattr(self.app, 'apply_theme_settings'):
                self.app.apply_theme_settings()
        else:
            new_data["active_tts_model"] = self.var_proj_model.get()
            # Zapisz do projektu (DB)
            for k, v in new_data.items():
                self.app.project.set_setting(k, v)
            # Odśwież lokalny konfig w pamięci app
            self.app.project.project_config.update(new_data)

        self.destroy()