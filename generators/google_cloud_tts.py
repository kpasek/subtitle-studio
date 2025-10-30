from typing import Optional
from .tts_base import TTSBase
from app.utils import is_installed

if is_installed('google.cloud.texttospeech'):
    import google.cloud.texttospeech as tts
else:
    # Pozwól na import pliku, ale rzuć błąd przy próbie użycia
    tts = None


class GoogleCloudTTS(TTSBase):
    """
    TTS implementation using Google Cloud Text-to-Speech API.
    """

    def __init__(self, credentials_path: str, voice_name: Optional[str] = None, language_code: str = "pl-PL"):
        """
        Initializes the Google Cloud TTS client.

        Args:
            credentials_path: Path to the Google Cloud service account .json credentials file.
            voice_name: The name of the voice to use (e.g., 'pl-PL-Wavenet-B').
            language_code: The language code (e.g., 'pl-PL').
        """
        if tts is None:
            raise ImportError("Pakiet 'google-cloud-texttospeech' nie jest zainstalowany.")

        self.credentials_path = credentials_path
        self.voice_name = voice_name
        self.language_code = language_code
        self.client = tts.TextToSpeechClient.from_service_account_file(
            credentials_path)

    @property
    def name(self) -> str:
        return "Google Cloud TTS"

    @property
    def is_online(self) -> bool:
        return True

    @property
    def settings(self) -> dict:
        return {
            "credentials_path": self.credentials_path,
            "voice_name": self.voice_name,
            "language_code": self.language_code
        }

    def get_available_voices(self):
        """Fetches available voices for the configured language."""
        response = self.client.list_voices(language_code=self.language_code)
        return response.voices

    def tts(self, text: str, output_path: str) -> str:
        """
        Generates speech and saves it as a .wav file.

        Args:
            text: The text to synthesize.
            output_path: The path to save the output .wav file.

        Returns:
            The output_path.
        """
        synthesis_input = tts.SynthesisInput(text=text)

        voice = tts.VoiceSelectionParams(
            language_code=self.language_code,
            name=self.voice_name
        )

        audio_config = tts.AudioConfig(
            # === ZMIANA: Zapis jako WAV (LINEAR16) ===
            audio_encoding=tts.AudioEncoding.LINEAR16,
            speaking_rate=1.0
        )

        response = self.client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )

        with open(output_path, "wb") as out:
            out.write(response.audio_content)

        return output_path