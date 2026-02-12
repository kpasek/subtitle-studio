from pydub import AudioSegment
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, Optional, Any, Callable
import threading


class AudioConverter:
    """
    Handles audio conversion, applying FFmpeg filters.
    """

    def __init__(self, filter_settings: Optional[Dict[str, Any]] = None, out_format: str = 'mp3'):
        """
        Initializes the converter.

        Args:
            filter_settings: A dictionary of filter configurations from global settings.
            out_format: Target output format ('ogg' or 'mp3').
        """
        self.filter_settings = filter_settings if filter_settings is not None else {}
        self.out_format = out_format.lower()

    def parse_ogg(self, input_file: str, output_file: str):
        """
        Converts a single audio file (.wav, .mp3, .ogg) to the target file
        in the /ready/ directory with filters applied.

        Args:
            input_file: Path to the source audio file.
            output_file: Path to the destination file.
        """

        if os.path.exists(output_file):
            return

        try:
            if input_file.lower().endswith('.ogg'):
                audio = AudioSegment.from_ogg(input_file)
            elif input_file.lower().endswith('.mp3'):
                audio = AudioSegment.from_mp3(input_file)
            else:
                audio = AudioSegment.from_wav(input_file)

            if not os.path.exists(output_file):
                self.export_file(audio, output_file)

        except Exception as e:
            print(f"Błąd podczas przetwarzania pliku {input_file}: {e}")
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                    print(f"Usunięto plik wyjściowy: {output_file}")
                except Exception as remove_err:
                    print(
                        f"Nie udało się usunąć pliku {output_file}: {remove_err}")
            raise e

    def export_file(self, audio: AudioSegment, output_file: str):
        """
        Eksportuje AudioSegment bezpośrednio do finalnego pliku,
        przekazując filtry i kodeki do FFmpeg za pomocą pydub.

        Args:
            audio: Obiekt Pydub AudioSegment.
            output_file: Docelowa ścieżka dla pliku.
        """
        filter_list = []
        filter_order = ['highpass', 'lowpass', 'deesser',
                        'acompressor', 'loudnorm', 'alimiter']

        for filter_name in filter_order:
            config = self.filter_settings.get(filter_name)
            if config and config.get("enabled", False):
                params = config.get("params")
                if params:
                    filter_list.append(f"{filter_name}={params}")

        filter_str = ",".join(filter_list)

        export_params = ['-loglevel', 'error']

        if self.out_format == 'mp3':
            target_format = 'mp3'
            codec_args = ['-c:a', 'libmp3lame', '-q:a', '2']
        else:
            target_format = 'ogg'
            codec_args = ['-c:a', 'libvorbis']

        if filter_str:
            export_params.extend(['-af', filter_str])
            export_params.extend(codec_args)
        else:
            export_params.extend(codec_args)

        try:
            audio.export(
                output_file,
                format=target_format,
                parameters=export_params
            )
        except Exception as e:
            print(f"Błąd FFmpeg podczas eksportu do {output_file}: {e}")
            raise e

    def build_output_file_path(self, filename: str, output_dir: str, out_format: str = 'ogg') -> str:
        """
        Constructs the standard 'output1 (ID).ext' path.

        Args:
            filename: The source filename.
            output_dir: The target directory.
            out_format: The target format ('mp3' or 'ogg').
        """
        base_name_match = os.path.splitext(filename)[0]
        if base_name_match.startswith("output1 "):
            base_name = base_name_match[8:]
        else:
            base_name = base_name_match

        ext = ".mp3" if out_format == 'mp3' else ".ogg"
        output_file_name = f"output1 {base_name}{ext}"

        output_path = os.path.join(output_dir, output_file_name)
        return output_path