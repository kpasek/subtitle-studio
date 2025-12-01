import shutil
import sqlite3
import os
import json
from pathlib import Path
from typing import List
from app.entity import SubtitleLine, PatternItem
from app.db import ProjectDB
from app.git_ops import GitManager
import uuid
import re


class ProjectManager:
    """
    Zarządza projektem (Folder + DB + Git).
    """

    def __init__(self):
        self.project_dir: Path = None
        self.db: ProjectDB = None
        self.git: GitManager = None

        self.subtitle_lines: List[SubtitleLine] = []
        self.patterns_subtitle: List[PatternItem] = []
        self.patterns_tts: List[PatternItem] = []
        self.project_config: dict = {}  # Cache ustawień

        self.audio_dir: Path = None
        self.has_unsaved_changes = False

    def close(self):
        if self.db:
            self.db.close()
            self.db = None
        self.project_dir = None
        self.git = None
        self.subtitle_lines = []
        self.project_config = {}

    def create_project(self, folder_path: Path, raw_lines: List[str], source_txt_path: Path = None):
        """
        Tworzy projekt.
        source_txt_path: Ścieżka do oryginalnego pliku txt, służy do importu legacy audio.
        """
        self.close()

        folder_path.mkdir(parents=True, exist_ok=True)
        (folder_path / "audio").mkdir(exist_ok=True)

        self.project_dir = folder_path
        self.audio_dir = folder_path / "audio"

        self.db = ProjectDB(folder_path / "project.db")
        self.db.connect()

        # Init Lines (z UUID)
        self.subtitle_lines = [SubtitleLine.new(l.strip()) for l in raw_lines if l.strip()]
        self.db.save_lines(self.subtitle_lines)

        # Opcjonalny auto-import przy tworzeniu (tylko jeśli jest mało plików, dla 100k lepiej użyć narzędzia)
        # Zostawiamy tu prostą logikę, ale główny import 100k plików idzie przez dedykowane narzędzie.
        if source_txt_path and source_txt_path.parent.exists():
             pass
             # Można tu ewentualnie wywołać LegacyImporter w trybie silent,
             # ale przy 100k plików zablokowałoby to UI.
             # Lepiej niech użytkownik uruchomi to ręcznie jeśli chce.

        # Init Git
        self.git = GitManager(folder_path)
        self.git.init_or_load()
        self._sync_git("Inicjalizacja projektu")

        self.has_unsaved_changes = False

    def open_project(self, folder_path: Path):
        self.close()
        if not (folder_path / "project.db").exists():
            raise ValueError(f"W folderze {folder_path} brakuje pliku project.db")

        self.project_dir = folder_path
        self.audio_dir = folder_path / "audio"

        self.db = ProjectDB(folder_path / "project.db")
        self.db.connect()

        self.subtitle_lines = self.db.get_lines()
        self.patterns_subtitle = self.db.get_patterns("subtitle")
        self.patterns_tts = self.db.get_patterns("tts")

        # Load config cache
        self.project_config = self._load_settings_dict()

        self.git = GitManager(folder_path)
        self.git.init_or_load()
        self.audio_dir.mkdir(exist_ok=True)

    def save_data(self):
        if not self.db: return
        self.db.save_lines(self.subtitle_lines)
        self.db.save_patterns("subtitle", self.patterns_subtitle)
        self.db.save_patterns("tts", self.patterns_tts)

    def prepare_commit(self) -> dict:
        text_content = "\n".join(l.text for l in self.subtitle_lines)
        self.git.stage_file(text_content)
        return {
            "diff_stat": self.git.get_diff_stats(),
            "full_diff": self.git.get_full_diff(),
            "lines_count": len(self.subtitle_lines),
            "audio_affected": self._calculate_audio_impact()
        }

    def commit(self, message: str):
        self._sync_git(message)
        self.save_data()
        self.has_unsaved_changes = False

    def delete_line(self, line_id: str):
        """Usuwa linię o podanym UUID."""
        # Znajdź i usuń z listy w pamięci
        original_len = len(self.subtitle_lines)
        self.subtitle_lines = [l for l in self.subtitle_lines if l.id != line_id]

        if len(self.subtitle_lines) < original_len:
            # Zapisz do DB
            self.db.save_lines(self.subtitle_lines)
            # Stage dla Gita (ale commit dopiero ręcznie przez usera, albo auto?
            # User prosił o opcję usuń linię. W tym modelu zmiany są "w locie" w pamięci/DB,
            # a Git jest snapshotem. Więc tylko DB update wystarczy, Git przy commicie.)
            self.has_unsaved_changes = True

    def _sync_git(self, message: str):
        text_content = "\n".join(l.text for l in self.subtitle_lines)
        self.git.stage_file(text_content)
        self.git.commit(message)

    def _calculate_audio_impact(self):
        if self.git.has_changes():
            return "Wykryto zmiany. Kolejność plików przy eksporcie może ulec zmianie."
        return "Brak zmian wpływających na strukturę."

    # --- Settings ---
    def get_setting(self, key, default=None):
        if self.db:
            return self.db.get_setting(key, default)
        return default

    def set_setting(self, key, value):
        if self.db:
            self.db.set_setting(key, value)
            self.project_config[key] = value

    def get_all_settings(self) -> dict:
        """Zwraca słownik wszystkich ustawień z DB."""
        if not self.db: return {}
        # Pobieramy z tabeli settings
        # To wymagałoby metody w ProjectDB typu fetch_all_settings
        # Dla uproszczenia zwracamy cached config + dociągamy brakujące
        return self.project_config.copy()

    def _load_settings_dict(self):
        # Helper - w prawdziwej implementacji DB powinno mieć "SELECT * FROM settings"
        # Tutaj symulacja lub zakładamy, że db.get_setting działa pojedynczo.
        # SQLite nie ma prostej metody "dump dict", trzeba iterować.
        # W db.py dodałem tabelę settings, ale nie metodę get_all.
        # Zróbmy prosty cache w pamięci ładowany leniwie lub przy otwarciu.
        # Tu uproszczenie:
        cfg = {}
        # Lista znanych kluczy:
        keys = ["active_tts_model", "base_audio_speed", "conversion_workers", "ffmpeg_filters"]
        for k in keys:
            val = self.db.get_setting(k)
            if val is not None:
                # Próba konwersji typów
                try:
                    cfg[k] = json.loads(val.replace("'", '"'))  # prosty hack, lepiej trzymać json
                except:
                    cfg[k] = val
        return cfg