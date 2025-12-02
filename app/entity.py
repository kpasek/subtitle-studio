import uuid
import time
from dataclasses import dataclass, asdict, field
from typing import List, Optional


@dataclass(slots=True)
class PatternItem:
    """
    Reprezentuje pojedynczy wzorzec regex (do wycinania lub zamiany).
    """
    pattern: str
    replace: str = ""
    case_sensitive: bool = True
    name: str | None = None
    enabled: bool = True

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> 'PatternItem':
        return cls(
            pattern=d.get("pattern", ""),
            replace=d.get("replace", ""),
            case_sensitive=d.get("case_sensitive", True),
            name=d.get("name", None),
            enabled=d.get("enabled", True)
        )


@dataclass(slots=True)
class SubtitleLine:
    """
    Reprezentuje pojedynczą linię dialogową z unikalnym identyfikatorem (UUID).
    Dzięki UUID zmiana treści nie gubi powiązania z plikiem audio.
    """
    id: str
    text: str

    @staticmethod
    def new(text: str) -> 'SubtitleLine':
        """Tworzy nową linię z losowym UUID."""
        return SubtitleLine(id=str(uuid.uuid4()), text=text)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> 'SubtitleLine':
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            text=d.get("text", "")
        )


@dataclass(slots=True)
class ProjectSnapshot:
    """
    Migawka stanu projektu do obsługi historii (Undo/Redo/Versions).
    """
    timestamp: float
    lines: List[SubtitleLine]
    description: str = ""

    def to_json(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "lines": [l.to_json() for l in self.lines],
            "description": self.description
        }

    @classmethod
    def from_json(cls, d: dict) -> 'ProjectSnapshot':
        lines = [SubtitleLine.from_json(l) for l in d.get("lines", [])]
        return cls(
            timestamp=d.get("timestamp", 0.0),
            lines=lines,
            description=d.get("description", "")
        )