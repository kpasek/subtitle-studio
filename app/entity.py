from dataclasses import dataclass, asdict


@dataclass
class PatternItem:
    pattern: str
    replace: str = ""
    case_sensitive: bool = True,
    name: str | None = None,
    enabled: bool = True

    def to_json(self):
        return asdict(self)

    @classmethod
    def from_json(cls, d):
        return cls(d.get("pattern", ""), d.get("replace", ""), d.get("case_sensitive", True), d.get("name", None), d.get("enabled", True))


@dataclass
class Line:
    original_text: str = ""  # Tekst oryginalny (niezmienny)
    text: str = ""  # Tekst po obróbce (do wyświetlania/napisów) - dawniej processed_clean
    tts_text: str = ""  # Tekst do syntezy mowy - dawniej processed_replace

    audio_duration: float = 0.0  # Długość wygenerowanego audio
    audio_filename: str = ""  # Nazwa pliku audio (np. output1 (1).wav)
    audio_similarity: float = 0.0  # Zgodność (np. 0.95)

    # Weryfikacja / metadane audio
    audio_status: str = ""  # MISSING/ERROR/OK/SHORT/etc.
    audio_format: str = ""  # WAV/MP3/OGG