import customtkinter as ctk
import json
import tkinter as tk
from pathlib import Path
from app.tooltip import CreateToolTip

DEFAULT_CONFIG = {
    "appearance_mode": "System",
    "color_theme": "blue",
    "conversion_workers": 4,
    "base_audio_speed": 1.1,
    "active_tts_model": "XTTS",
    "default_tts_model": "XTTS",
    "ffmpeg_filters": {
        "highpass": {"enabled": False, "params": "f=200"},
        "lowpass": {"enabled": False, "params": "f=3000"},
        "acompressor": {"enabled": False, "params": "threshold=-12dB:ratio=2:attack=20:release=100"},
        "loudnorm": {"enabled": False, "params": "I=-16:TP=-1.5:LRA=11"},
        "silenceremove": {"enabled": False, "params": "stop_periods=-1:stop_duration=1:stop_threshold=-60dB"}
    },
    "recent_projects": []
}

AVAILABLE_FILTERS = [
    ("highpass", "Filtr górnoprzepustowy", "Usuwa niskie częstotliwości (np. buczenie). Domyślnie < 200Hz.", "f=200"),
    ("lowpass", "Filtr dolnoprzepustowy", "Usuwa wysokie częstotliwości (np. szum). Domyślnie > 3000Hz.", "f=3000"),
    ("acompressor", "Kompresor", "Wyrównuje głośność, ścisza najgłośniejsze fragmenty.",
     "threshold=-12dB:ratio=2:attack=20:release=100"),
    ("loudnorm", "Normalizacja głośności (EBU R128)", "Dostosowuje głośność do standardu nadawczego (wyrównuje audio).",
     "I=-16:TP=-1.5:LRA=11"),
    ("silenceremove", "Usuwanie ciszy (Końcowej)", "Przycina ciszę na końcu pliku.",
     "stop_periods=-1:stop_duration=1:stop_threshold=-60dB")
]


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, torch_available: bool, mode: str = 'global'):
        super().__init__(master)
        self.title("Ustawienia " + ("Globalne" if mode == 'global' else "Projektu"))
        self.geometry("600x650")
        self.transient(master)
        self.lift()
        self.app = master
        self.mode = mode
        self.torch_available = torch_available
        self.filter_vars = {}

        # Load Logic
        if mode == 'global':
            self.current_config = self.app.global_config.copy()
        else:
            self.current_config = self.app.project.get_all_settings()
            # Merge defaults if missing
            for k, v in DEFAULT_CONFIG.items():
                if k not in self.current_config:
                    self.current_config[k] = v

        # Ensure filters dict exists
        if 'ffmpeg_filters' not in self.current_config:
            self.current_config['ffmpeg_filters'] = DEFAULT_CONFIG['ffmpeg_filters'].copy()

        self._create_widgets()

    def _create_widgets(self):
        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

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

        # Filtry
        ctk.CTkLabel(scroll, text="Filtry FFmpeg:", font=("", 14, "bold")).pack(anchor="w", pady=(15, 5))

        current_filters = self.current_config.get("ffmpeg_filters", {})
        # Jeśli string (błąd zapisu wcześniej), napraw na dict
        if isinstance(current_filters, str):
            try:
                current_filters = json.loads(current_filters)
            except:
                current_filters = DEFAULT_CONFIG['ffmpeg_filters']

        filters_frame = ctk.CTkFrame(scroll)
        filters_frame.pack(fill="x", pady=5)

        for key, name, tooltip_text, default_params in AVAILABLE_FILTERS:
            row = ctk.CTkFrame(filters_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            # Pobierz stan
            is_enabled = False
            if key in current_filters:
                val = current_filters[key]
                if isinstance(val, dict):
                    is_enabled = val.get("enabled", False)

            var = tk.BooleanVar(value=is_enabled)
            self.filter_vars[key] = (var, default_params)

            cb = ctk.CTkCheckBox(row, text=name, variable=var)
            cb.pack(side="left", padx=5)
            CreateToolTip(cb, tooltip_text)

        btn_frame = ctk.CTkFrame(self)
        btn_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(btn_frame, text="Anuluj", command=self.destroy, fg_color="gray").pack(side="left", expand=True,
                                                                                            padx=5)
        ctk.CTkButton(btn_frame, text="Zapisz", command=self.save, fg_color="green").pack(side="right", expand=True,
                                                                                          padx=5)

    def save(self):
        new_filters = {}
        for key, (var, default_params) in self.filter_vars.items():
            new_filters[key] = {
                "enabled": var.get(),
                "params": default_params
            }

        try:
            bs = float(self.var_speed.get())
            cw = int(self.var_workers.get())
        except ValueError:
            return

        new_data = {
            "base_audio_speed": bs,
            "conversion_workers": cw,
            "ffmpeg_filters": new_filters
        }

        if self.mode == 'global':
            new_data["appearance_mode"] = self.var_theme.get()
            new_data["color_theme"] = self.var_color.get()
            new_data["default_tts_model"] = self.var_default_model.get()
            self.app.save_global_config(new_data)
            if hasattr(self.app, 'apply_theme_settings'):
                self.app.apply_theme_settings()
        else:
            new_data["active_tts_model"] = self.var_proj_model.get()
            for k, v in new_data.items():
                self.app.project.set_setting(k, v)
            self.app.project.project_config.update(new_data)

        self.destroy()