from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class PatternItem:
    """
    Reprezentuje pojedynczy wzorzec regex.
    Pole 'applied' wskazuje, czy wzorzec został oznaczony jako zastosowany (zgodnie z wymaganiami).
    """
    pattern: str
    replace: str = ""
    case_sensitive: bool = True
    name: str | None = None
    enabled: bool = True  # Czy jest aktywny w konfiguracji
    applied: bool = False  # "informacja wzorzec został już zastosowany"
    type: str = "subtitle"  # 'subtitle' lub 'tts'
    id: Optional[int] = None

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> 'PatternItem':
        return cls(
            pattern=d.get("pattern", ""),
            replace=d.get("replace", ""),
            case_sensitive=d.get("case_sensitive", True),
            name=d.get("name", None),
            enabled=d.get("enabled", True),
            applied=d.get("applied", False),
            type=d.get("type", "subtitle"),
            id=d.get("id")
        )


@dataclass
class SubtitleLine:
    """
    Złożony obiekt reprezentujący linię w trzech stanach:
    1. Oryginał (niezmienny po imporcie)
    2. Wersja pod napisy (Modified Subtitle)
    3. Wersja pod lektora (Modified TTS)
    """
    id: Optional[int]  # ID z bazy danych (Integer)
    original_text: str

    # Wersja dla napisów (Game Reader / wyświetlanie)
    subtitle_text: str
    # Wersja dla TTS (Generowanie audio)
    tts_text: str

    subtitle_change_source: str = "NONE"
    tts_change_source: str = "NONE"

    ord: int = 0  # Kolejność sortowania

    @staticmethod
    def new(text: str, order: int = 0) -> 'SubtitleLine':
        """Tworzy nową linię. ID zostanie nadane przez bazę danych przy zapisie."""
        return SubtitleLine(
            id=None,
            original_text=text,
            subtitle_text=text,
            tts_text=text,
            ord=order
        )