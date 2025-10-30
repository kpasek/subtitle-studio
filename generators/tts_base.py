from abc import ABC, abstractmethod
from typing import Optional


class TTSBase(ABC):
    """
    Abstract base class for all Text-to-Speech (TTS) implementations.
    Defines the common interface for generating speech from text.
    """

    @abstractmethod
    def tts(self, text: str, output_path: str) -> str:
        """
        Generates speech from text and saves it to a file.

        The output file should ideally be a .wav file (LINEAR16)
        as this is the format expected by the AudioConverter.

        Args:
            text: The text to be synthesized.
            output_path: The full path where the audio file should be saved.

        Returns:
            str: The path to the generated audio file (output_path).
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """The user-friendly name of the TTS model (e.g., "XTTS", "ElevenLabs")."""
        pass

    @property
    @abstractmethod
    def is_online(self) -> bool:
        """Whether the model requires an internet connection (True) or runs locally (False)."""
        pass

    @property
    def settings(self) -> dict:
        """
        Returns a dictionary of the model's current settings (e.g., API keys, voice IDs).
        Primarily for debugging or informational purposes.
        """
        return {}