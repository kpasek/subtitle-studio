from pathlib import Path
from typing import List
from app.entity import SubtitleLine, PatternItem
from app.db import ProjectDB
from app.git_ops import GitManager
from app.text_processing import  apply_replace_patterns


class ProjectManager:
    """
    Zarządza projektem (Folder + DB + Git).
    Nowa wersja obsługująca strukturę 3-tabelową.
    """

    def __init__(self):
        self.project_dir: Path = None
        self.db: ProjectDB = None
        self.git: GitManager = None

        self.subtitle_lines: List[SubtitleLine] = []

        # Wzorce trzymamy w pamięci
        self.patterns_subtitle: List[PatternItem] = []
        self.patterns_tts: List[PatternItem] = []

        self.project_config: dict = {}
        self.audio_dir: Path = None
        self.has_unsaved_changes = False

    def close(self):
        if self.db:
            self.db.close()
            self.db = None
        self.project_dir = None
        self.git = None
        self.subtitle_lines = []
        self.patterns_subtitle = []
        self.patterns_tts = []
        self.project_config = {}

    def create_project(self, folder_path: Path, raw_lines: List[str], source_txt_path: Path = None):
        """
        Tworzy projekt w nowej strukturze.
        1. Inicjalizuje bazę.
        2. Wstawia surowe linie do `original_lines` i domyślnie kopiuje je do tabel `modified`.
        3. Przeładowuje linie z bazy, aby uzyskać nadane ID (Integer).
        """
        self.close()

        folder_path.mkdir(parents=True, exist_ok=True)
        (folder_path / "audio").mkdir(exist_ok=True)

        self.project_dir = folder_path
        self.audio_dir = folder_path / "audio"

        self.db = ProjectDB(folder_path / "project.db")
        self.db.connect()

        # Tworzenie obiektów w pamięci
        # SubtitleLine.new ustawia ID na None, baza nada auto-increment
        init_lines = [SubtitleLine.new(l.strip(), idx) for idx, l in enumerate(raw_lines) if l.strip()]

        # Zapis do bazy (to nada ID)
        self.db.save_lines(init_lines)

        # Przeładowanie z bazy, aby mieć poprawne ID w pamięci
        self.subtitle_lines = self.db.get_lines()

        # Inicjalizacja Gita
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

        # Wczytanie danych
        self.subtitle_lines = self.db.get_lines()
        self.patterns_subtitle = self.db.get_patterns("subtitle")
        self.patterns_tts = self.db.get_patterns("tts")

        self.project_config = self._load_settings_dict()

        self.git = GitManager(folder_path)
        self.git.init_or_load()
        self.audio_dir.mkdir(exist_ok=True)

    def save_data(self):
        """Zapisuje aktualny stan linii i wzorców do bazy."""
        if not self.db: return
        self.db.save_lines(self.subtitle_lines)
        self.db.save_patterns(self.patterns_subtitle)  # Zapisuje listę subtitle
        self.db.save_patterns(self.patterns_tts)  # Zapisuje listę tts

    def apply_patterns_and_save(self, mode: str):
        """
        Aplikuje aktywne wzorce do odpowiedniej kolumny tekstowej
        i oznacza wzorce jako zastosowane (applied=True).
        mode: 'subtitle' lub 'tts'
        """
        patterns = self.patterns_subtitle if mode == 'subtitle' else self.patterns_tts

        # Filtrujemy tylko włączone wzorce
        active_patterns = [p for p in patterns if p.enabled]
        if not active_patterns:
            return 0

        count_changed = 0

        # Iterujemy po liniach
        for line in self.subtitle_lines:
            old_text = line.subtitle_text if mode == 'subtitle' else line.tts_text

            # Logika aplikowania
            # Dla subtitle używamy 'remove' (czyli replace na pusty ciąg, lub replace jeśli zdefiniowany)
            # Dla tts używamy 'replace'
            # Funkcje pomocnicze text_processing obsługują to generycznie,
            # ale tutaj musimy zaktualizować konkretne pole w obiekcie.

            # Używamy funkcji pomocniczej na pojedynczym stringu
            # Uwaga: helpery przyjmują listę, więc pakujemy w listę
            if mode == 'subtitle':
                # Subtitle (Game Reader) - zazwyczaj czyszczenie
                # Tutaj zakładamy, że patterns_subtitle mogą usuwać lub podmieniać
                res = apply_replace_patterns([old_text], active_patterns)
                new_text = res[0]

                if new_text != old_text:
                    line.subtitle_text = new_text
                    line.subtitle_change_source = "PATTERN"
                    count_changed += 1
            else:
                # TTS - podmiana pod lektora
                res = apply_replace_patterns([old_text], active_patterns)
                new_text = res[0]

                if new_text != old_text:
                    line.tts_text = new_text
                    line.tts_change_source = "PATTERN"
                    count_changed += 1

        # Oznaczamy wzorce jako zastosowane
        for p in active_patterns:
            p.applied = True

        self.save_data()
        return count_changed

    def update_manual_edit(self, line_index: int, new_text: str, mode: str):
        """Aktualizuje tekst po edycji ręcznej."""
        if line_index < 0 or line_index >= len(self.subtitle_lines):
            return

        line = self.subtitle_lines[line_index]

        if mode == 'subtitle':
            if line.subtitle_text != new_text:
                line.subtitle_text = new_text
                line.subtitle_change_source = "MANUAL"
        elif mode == 'tts':
            if line.tts_text != new_text:
                line.tts_text = new_text
                line.tts_change_source = "MANUAL"

    def prepare_commit(self) -> dict:
        # Generujemy podgląd pliku tekstowego (używamy wersji subtitle/original jako referencji dla Gita)
        # Git ma śledzić historię zmian tekstowych.
        text_content = "\n".join(l.subtitle_text for l in self.subtitle_lines)
        self.git.stage_file(text_content)
        return {
            "diff_stat": self.git.get_diff_stats(),
            "full_diff": self.git.get_full_diff(),
            "lines_count": len(self.subtitle_lines),
            "audio_affected": "Sprawdź spójność ID"
        }

    def commit(self, message: str):
        self._sync_git(message)
        self.save_data()
        self.has_unsaved_changes = False

    def _sync_git(self, message: str):
        text_content = "\n".join(l.subtitle_text for l in self.subtitle_lines)
        self.git.stage_file(text_content)
        self.git.commit(message)

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
        return self.project_config.copy()

    def _load_settings_dict(self):
        cfg = {}
        keys = ["active_tts_model", "base_audio_speed", "conversion_workers", "ffmpeg_filters"]
        for k in keys:
            val = self.db.get_setting(k)
            if val is not None:
                # db.get_setting zwraca już poprawne typy dzięki tabeli settings
                cfg[k] = val
        return cfg