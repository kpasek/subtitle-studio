import shutil
from pathlib import Path
from typing import List
from app.entity import SubtitleLine, PatternItem
from app.db import ProjectDB
from app.git_ops import GitManager
import uuid


class ProjectManager:
    def __init__(self):
        self.project_dir: Path = None
        self.db: ProjectDB = None
        self.git: GitManager = None

        self.subtitle_lines: List[SubtitleLine] = []
        self.patterns_subtitle: List[PatternItem] = []  # Dawne custom_remove
        self.patterns_tts: List[PatternItem] = []  # Dawne custom_replace

        self.audio_dir: Path = None
        self.has_unsaved_changes = False

    def create_project(self, folder_path: Path, raw_lines: List[str]):
        """Tworzy nową strukturę projektu."""
        folder_path.mkdir(parents=True, exist_ok=True)
        (folder_path / "audio").mkdir(exist_ok=True)

        self.project_dir = folder_path
        self.audio_dir = folder_path / "audio"

        # Init DB
        self.db = ProjectDB(folder_path / "project.db")
        self.db.connect()

        # Init Lines
        self.subtitle_lines = [SubtitleLine.new(l.strip()) for l in raw_lines if l.strip()]
        self.db.save_lines(self.subtitle_lines)

        # Init Git
        self.git = GitManager(folder_path)
        self.git.init_or_load()
        self.git.stage_file("\n".join(l.text for l in self.subtitle_lines))
        self.git.commit("Inicjalizacja projektu")

    def open_project(self, folder_path: Path):
        if not (folder_path / "project.db").exists():
            raise ValueError("To nie jest folder projektu (brak project.db)")

        self.project_dir = folder_path
        self.audio_dir = folder_path / "audio"

        self.db = ProjectDB(folder_path / "project.db")
        self.db.connect()

        self.subtitle_lines = self.db.get_lines()
        self.patterns_subtitle = self.db.get_patterns("subtitle")
        self.patterns_tts = self.db.get_patterns("tts")

        self.git = GitManager(folder_path)
        self.git.init_or_load()

        # Sync plików audio (czy istnieją) - opcjonalne

    def save_data(self):
        """Zapisuje stan do DB (bez commita git)."""
        self.db.save_lines(self.subtitle_lines)
        self.db.save_patterns("subtitle", self.patterns_subtitle)
        self.db.save_patterns("tts", self.patterns_tts)

    def prepare_commit(self) -> dict:
        """Przygotowuje diff przed commitem."""
        text_content = "\n".join(l.text for l in self.subtitle_lines)
        self.git.stage_file(text_content)

        stats = {
            "diff_stat": self.git.get_diff_stats(),
            "full_diff": self.git.get_full_diff(),
            "lines_count": len(self.subtitle_lines),
            # Szacowanie wpływu na audio
            "audio_affected": self._calculate_audio_impact()
        }
        return stats

    def commit(self, message: str):
        self.git.commit(message)
        self.save_data()  # Update DB
        self.has_unsaved_changes = False

    def _calculate_audio_impact(self):
        """Sprawdza ile plików audio (indeksowanych) ulegnie zmianie."""
        # W modelu UUID źródłowe pliki się nie zmieniają.
        # Zmienia się tylko mapowanie przy eksporcie (1.ogg, 2.ogg).
        # Dla usera: "Przesunięcie indeksów nastąpi dla X plików".
        # To wymagałoby porównania ze stanem poprzednim, co jest trudne bez parsowania diffa.
        # Zwracamy uproszczoną informację.
        return "Zmiana kolejności wpłynie na eksportowane pliki (ready/)."

    def close(self):
        if self.db: self.db.close()