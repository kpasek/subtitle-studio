from dataclasses import dataclass, asdict, field
import uuid


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
    audio_transcribed_text: str = ""  # Tekst odczytany z audio (cache)

    # Weryfikacja / metadane audio
    audio_status: str = ""  # MISSING/ERROR/OK/SHORT/etc.
    audio_format: str = ""  # WAV/MP3/OGG
    audio_hallucination: str = ""  # Flag for TTS hallucinations (silence, buzzing)
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def get_text(self) -> str:
        """Zwraca text. Jeśli equals original_text, zwraca original_text."""
        if not self.text:
            return self.original_text
        return self.text

    def get_tts_text(self) -> str:
        """Zwraca tts_text. Jeśli equals text, zwraca text."""
        if self.tts_text:
            return self.tts_text
        return self.get_text()

    def set_text(self, value: str):
        """Ustawia text. Jeśli equals original_text, czyści text."""
        if value == self.original_text:
            self.text = ""
        else:
            self.text = value

    def set_tts_text(self, value: str):

        """Ustawia tts_text. Jeśli equals text, czyści tts_text."""
        if value == self.text:
            self.tts_text = ""
        else:
            self.tts_text = value
    
    def calculate_cps(self) -> float:
        """
        Oblicza ilość znaków na sekundę (CSP - Character Per Second).

        Jeśli długość audio jest większa niż 0, zwraca długość tekstu podzieloną przez
        długość audio. W przeciwnym wypadku zwraca 0.
        """
        if self.audio_duration > 0:
            txt = self.get_tts_text().strip('.?!')
            from collections import Counter
            stats = Counter(txt)
            short = stats[','] + stats['-']
            long = stats['.'] + stats['!'] + stats['?']
            pauses = (short * 0.4) + (long * 0.6)
            return len(txt) / (self.audio_duration - pauses) if (self.audio_duration - pauses) > 0 else 0.0
        return 0.0