from typing import Optional, List
from .tts_base import TTSBase
from app.utils import is_installed

if is_installed('elevenlabs'):
    from elevenlabs.client import ElevenLabs
    from elevenlabs import Voice, save # Import save
else:
    # Zapewnij typy zastępcze
    ElevenLabs = None
    Voice = None
    save = None


class ElevenLabsTTS(TTSBase):
    """
    TTS implementation using the ElevenLabs API.
    """

    def __init__(self, api_key: str, voice_id: Optional[str] = None):
        """
        Initializes the ElevenLabs client.

        Args:
            api_key: The ElevenLabs API key.
            voice_id: The ID of the voice to use.
        """
        if ElevenLabs is None:
            raise ImportError("Pakiet 'elevenlabs' nie jest zainstalowany.")

        self.api_key = api_key
        self.client = ElevenLabs(api_key=api_key)

        self.voice_id = voice_id
        self._voices = None

    @property
    def name(self) -> str:
        return "ElevenLabs"

    @property
    def is_online(self) -> bool:
        return True

    @property
    def settings(self) -> dict:
        return {
            "api_key": self.api_key,
            "voice_id": self.voice_id
        }

    @property
    def available_voices(self) -> List[Voice]:
        """Lazily fetches the list of available voices from the API."""
        if self._voices is None:
            response = self.client.voices.get_all()
            self._voices = response.voices
        return self._voices

    def tts(self, text: str, output_path: str) -> str:
        """
        Generates speech and saves it as an audio file.
        The output format requested is mp3, but saved with a .wav extension
        for compatibility with the converter pipeline. Pydub handles the format.

        Args:
            text: The text to synthesize.
            output_path: The path to save the output audio file (e.g., "output.wav").

        Returns:
            The output_path.
        """
        if not self.voice_id:
            raise ValueError("Voice ID not set for ElevenLabs")

        audio_data = b""
        audio_stream = self.client.text_to_speech.convert(
            text=text,
            voice_id=self.voice_id,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )

        for chunk in audio_stream:
            audio_data += chunk

        with open(output_path[:-4]+".mp3", 'wb') as f:
            f.write(audio_data)

        return output_path