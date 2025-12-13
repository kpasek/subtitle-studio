from pydub import AudioSegment
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, Optional, Any, Callable
import threading


def _convert_worker(task_args):
    """
    Funkcja robocza (top-level) dla puli procesów.
    Tworzy własną instancję konwertera i wywołuje parse_ogg.
    """
    # ZMIANA: Dodano out_format do argumentów
    input_file, output_file, filter_settings, out_format = task_args

    print(f"[Worker] Przetwarzam: {input_file} -> {output_file} (format: {out_format})")

    try:
        # ZMIANA: Przekazujemy out_format do konstruktora
        converter_instance = AudioConverter(filter_settings=filter_settings, out_format=out_format)
        converter_instance.parse_ogg(input_file, output_file)
        return (input_file, True, None)
    except Exception as e:
        print(f"[Worker] Błąd podczas przetwarzania {input_file}: {e}")
        return (input_file, False, str(e))


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

    def convert_dir(self, audio_dir: str, output_dir: str, max_workers: int = 4,
                    progress_callback: Optional[Callable[[
                        int, int], None]] = None,
                    cancel_event: Optional[threading.Event] = None, out_format: str = 'mp3'):
        """
        Converts all audio files in `audio_dir` (excluding /ready/)
        and saves them to `output_dir` using a process pool.
        """
        self.out_format = out_format

        tasks = []
        os.makedirs(output_dir, exist_ok=True)

        print(f"Rozpoczynam skanowanie {audio_dir} dla konwersji (format: {out_format})...")

        for filename in os.listdir(audio_dir):
            if filename.lower().endswith((".wav", ".ogg", ".mp3")):
                if filename.lower().endswith(".temp.ogg"):
                    continue

                input_path = os.path.join(audio_dir, filename)

                # ZMIANA: Przekazujemy out_format do budowania ścieżki
                output_path_final = self.build_output_file_path(
                    filename, output_dir, out_format)

                if os.path.exists(output_path_final):
                    continue

                # ZMIANA: Przekazujemy out_format w krotce argumentów
                task_args = (input_path, output_path_final, self.filter_settings, out_format)
                tasks.append(task_args)

        if not tasks:
            print(f"Nie znaleziono plików do konwersji w {audio_dir}.")
            if progress_callback:
                progress_callback(1, 1)
            return

        print(
            f"Znaleziono {len(tasks)} plików do przetworzenia. Używam {max_workers} procesów.")

        successful_count = 0
        failed_count = 0
        total_tasks = len(tasks)

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(
                _convert_worker, task_args): task_args for task_args in tasks}

            for i, future in enumerate(as_completed(futures)):
                task_args = futures[future]
                input_file = task_args[0]

                if cancel_event and cancel_event.is_set():
                    print("Anulowanie konwersji wymuszone przez użytkownika.")
                    for remaining_future in futures:
                        remaining_future.cancel()
                    break

                try:
                    _, success, error_msg = future.result()
                    if success:
                        successful_count += 1
                    else:
                        failed_count += 1
                        print(f"NIE POWIODŁO SIĘ: {input_file} -> {error_msg}")
                except Exception as e:
                    failed_count += 1
                    print(
                        f"NIE POWIODŁO SIĘ (Błąd 'future'): {input_file} -> {e}")

                if progress_callback and successful_count % 20 == 0:
                    try:
                        progress_callback(i + 1, total_tasks)
                    except Exception as e:
                        print(f"Błąd w progress_callback: {e}")

            if cancel_event and cancel_event.is_set():
                print("Proces konwersji zakończony anulowaniem.")
            else:
                print(f"✅ Zakończono przetwarzanie dla {audio_dir}.")
                print(
                    f"Pomyślnie: {successful_count}, Nie powiodło się: {failed_count}")
                if progress_callback:
                    progress_callback(total_tasks, total_tasks)

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