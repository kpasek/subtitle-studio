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
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
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
    audio_hallucination: str = "PENDING"  # Flag for TTS hallucinations (silence, buzzing)


    def get_text(self) -> str:
        """
        Returns the text. If it is equal to original_text, returns original_text.

        Args:
            None

        Returns:
            str: The text or original_text if they are equal
        """
        if not self.text:
            return self.original_text
        return self.text

    def get_tts_text(self) -> str:
        """
        Returns the tts_text. If it is equal to text, returns text.

        Args:
            None

        Returns:
            str: The tts_text or text if they are equal
        """
        if self.tts_text:
            return self.tts_text
        return self.get_text()
    
    def get_original_text(self) -> str:
        """
        Returns the original_text.

        Args:
            None

        Returns:
            str: The original text
        """
        return self.original_text

    def set_text(self, value: str):
        """
        Sets the text. If it is equal to original_text, clears text.
        Args:
            value (str): The new text

        Returns:
            None
        """
        if value == self.original_text:
            self.text = ""
        else:
            self.text = value

    def set_tts_text(self, value: str):
        """
        Sets the tts_text. If it is equal to text, clears tts_text.

        Args:
            value (str): The new tts_text

        Returns:
            None
        """
        if self.tts_text:
            return self.tts_text
        return self.get_text()
    
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