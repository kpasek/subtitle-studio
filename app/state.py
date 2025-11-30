import json
import time
import uuid
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from app.entity import SubtitleLine, ProjectSnapshot, PatternItem
from app.text_processing import reconcile_lines


class ProjectStateManager:
    """
    Zarządza stanem danych aplikacji.
    """

    def __init__(self):
        self.project_path: Optional[Path] = None
        self.subtitle_lines: List[SubtitleLine] = []
        self.history: List[ProjectSnapshot] = []
        self.current_history_index: int = -1

        self.project_config: dict = {}
        self.custom_remove: List[PatternItem] = []
        self.custom_replace: List[PatternItem] = []

        self.audio_dir: Optional[Path] = None
        self.has_unsaved_changes: bool = False

    def initialize_new_project(self, raw_text_lines: List[str]):
        """Inicjalizuje czysty stan dla nowego projektu z surowego tekstu."""
        # Konwersja tekstu na obiekty z UUID
        self.subtitle_lines = [
            SubtitleLine.new(line.strip())
            for line in raw_text_lines
            if line.strip()
        ]

        # Reset historii
        self.history = []
        self.current_history_index = -1

        # Reset konfiguracji
        self.project_config = {
            "created_at": str(datetime.now())
        }
        self.custom_remove = []
        self.custom_replace = []
        self.project_path = None
        self.has_unsaved_changes = True

        # Utwórz pierwszy snapshot
        self.commit_text_changes([l.text for l in self.subtitle_lines])

    def load_project(self, path: Path) -> None:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.project_path = path
        self.project_config = data.get('config', {})

        self.history = [ProjectSnapshot.from_json(s) for s in data.get('history', [])]

        if self.history:
            self.current_history_index = len(self.history) - 1
            self.subtitle_lines = self.history[self.current_history_index].lines
        else:
            self.subtitle_lines = []
            self.current_history_index = -1

        self.custom_remove = [PatternItem.from_json(x) for x in data.get("custom_remove", [])]
        self.custom_replace = [PatternItem.from_json(x) for x in data.get("custom_replace", [])]

        if "audio_path" in self.project_config:
            self.audio_dir = Path(self.project_config["audio_path"])

        self.has_unsaved_changes = False

    def save_project(self, target_path: Optional[Path] = None) -> Path:
        save_path = target_path or self.project_path
        if not save_path:
            raise ValueError("Brak ścieżki do zapisu")

        data = {
            "config": self.project_config,
            "custom_remove": [p.to_json() for p in self.custom_remove],
            "custom_replace": [p.to_json() for p in self.custom_replace],
            "history": [s.to_json() for s in self.history]
        }

        if self.audio_dir:
            data["config"]["audio_path"] = str(self.audio_dir)

        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.project_path = save_path
        self.has_unsaved_changes = False
        return save_path

    def commit_text_changes(self, new_text_lines: List[str]) -> int:
        new_lines = reconcile_lines(self.subtitle_lines, new_text_lines)

        snapshot = ProjectSnapshot(
            timestamp=time.time(),
            lines=new_lines,
            description=f"Zmiana {datetime.now().strftime('%H:%M:%S')}"
        )

        self.history.append(snapshot)
        self.current_history_index = len(self.history) - 1
        self.subtitle_lines = new_lines
        self.has_unsaved_changes = True
        return len(new_lines)

    def restore_snapshot(self, index: int) -> None:
        if 0 <= index < len(self.history):
            self.subtitle_lines = self.history[index].lines
            self.current_history_index = index
            self.has_unsaved_changes = True

    def get_raw_text(self) -> str:
        return "\n".join(line.text for line in self.subtitle_lines)

    def export_patterns_to_csv(self, path: Path, ptype: str):
        target = self.custom_remove if ptype == 'remove' else self.custom_replace
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            for item in target:
                writer.writerow([item.pattern, item.replace])