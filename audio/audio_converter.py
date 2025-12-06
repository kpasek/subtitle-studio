from pydub import AudioSegment
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
import math
from typing import Dict, Optional, Any, Callable
import subprocess
import sys
import threading


def _convert_worker(task_args):
    """
    Funkcja robocza (top-level) dla puli procesów.
    Tworzy własną instancję konwertera i wywołuje parse_ogg.
    """
    input_file, output_file, filter_settings = task_args

    print(f"[Worker] Przetwarzam: {input_file} -> {output_file}")

    try:
        converter_instance = AudioConverter(filter_settings=filter_settings)
        converter_instance.parse_ogg(input_file, output_file)
        return (input_file, True, None)
    except Exception as e:
        print(f"[Worker] Błąd podczas przetwarzania {input_file}: {e}")
        return (input_file, False, str(e))


class AudioConverter:
    """
    Handles audio conversion, applying FFmpeg filters.
    """

    def __init__(self, filter_settings: Optional[Dict[str, Any]] = None):
        """
        Initializes the converter.

        Args:
            filter_settings: A dictionary of filter configurations from global settings.
        """
        self.filter_settings = filter_settings if filter_settings is not None else {}

    def parse_ogg(self, input_file: str, output_file: str):
        """
        Converts a single audio file (.wav, .mp3, .ogg) to two .ogg files
        in the /ready/ directory (output1) with filters applied.

        Args:
            input_file: Path to the source audio file.
        """

        input_filename = os.path.basename(input_file)
        input_dir = os.path.dirname(output_file)

        base_name_match = os.path.splitext(input_filename)[0]
        if base_name_match.startswith("output1 "):
            base_name = base_name_match[8:]
        else:
            base_name = base_name_match


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
            # Rzuć błąd dalej, aby _convert_worker go złapał
            raise e

    def export_file(self, audio: AudioSegment, output_file: str):
        """
        Eksportuje AudioSegment bezpośrednio do finalnego pliku .ogg,
        przekazując filtry i prędkość do FFmpeg za pomocą pydub.

        Args:
            audio: Obiekt Pydub AudioSegment.
            output_file: Docelowa ścieżka dla pliku .ogg.
        """

        # 1. Budowanie łańcucha filtrów (tak jak wcześniej)
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

        if filter_str:
            final_filter_chain = filter_str
        else:
            final_filter_chain = ""
        export_params = ['-loglevel', 'error']

        if final_filter_chain:
            export_params.extend(['-af', final_filter_chain])
            export_params.extend(['-c:a', 'libvorbis'])
        else:
            pass

        # 3. Wykonanie eksportu w jednym kroku
        #    Nie ma już pliku .temp.ogg ani bloku subprocess.
        try:
            audio.export(
                output_file,
                format="ogg",
                parameters=export_params
            )
        except Exception as e:
            # Łapiemy błąd, jeśli pydub/ffmpeg zawiedzie
            print(f"Błąd FFmpeg/Pydub podczas eksportu do {output_file}: {e}")
            # Rzuć błąd dalej, aby parse_ogg i _convert_worker go złapały
            raise e
            
    def convert_dir(self, audio_dir: str, output_dir: str, max_workers: int = 4,
                    progress_callback: Optional[Callable[[
                        int, int], None]] = None,
                    cancel_event: Optional[threading.Event] = None):
        """
        Converts all audio files in `audio_dir` (excluding /ready/)
        and saves them to `output_dir` using a process pool.

        Args:
            audio_dir: Source directory with raw .wav/.mp3/.ogg files.
            output_dir: Target directory (usually '.../ready/').
            max_workers: The number of processes to use.
            progress_callback: Optional function to call with (current, total) progress.
        """
        tasks = []
        os.makedirs(output_dir, exist_ok=True)

        print(f"Rozpoczynam skanowanie {audio_dir} dla konwersji...")

        for filename in os.listdir(audio_dir):
            if filename.lower().endswith((".wav", ".ogg", ".mp3")):
                if filename.lower().endswith(".temp.ogg"):
                    continue

                input_path = os.path.join(audio_dir, filename)
                output_path_ogg = self.build_output_file_path(
                    filename, output_dir)

                base_name_match = os.path.splitext(filename)[0]
                if base_name_match.startswith("output1 "):
                    base_name = base_name_match[8:]
                else:
                    base_name = base_name_match

                if os.path.exists(output_path_ogg) :
                    continue

                task_args = (input_path, output_path_ogg, self.filter_settings)
                tasks.append(task_args)

        if not tasks:
            print(f"Nie znaleziono plików do konwersji w {audio_dir}.")
            print(
                f"✅ Zakończono przetwarzanie wszystkich plików audio dla {audio_dir}")
            if progress_callback:
                progress_callback(1, 1)  # Pokaż 100% jeśli nie ma zadań
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
                    # Anuluj wszystkie oczekujące zadania (nie są one jeszcze uruchomione)
                    for remaining_future in futures:
                        remaining_future.cancel()
                    break  # Wyjdź z pętli as_completed

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
                # Nie rzucamy wyjątku, tylko kończymy normalnie.
            else:
                print(f"✅ Zakończono przetwarzanie dla {audio_dir}.")
                print(
                    f"Pomyślnie: {successful_count}, Nie powiodło się: {failed_count}")
                # Upewnij się, że pasek postępu pokazuje 100% po zakończeniu
                if progress_callback:
                    progress_callback(total_tasks, total_tasks)

    def build_output_file_path(self, filename: str, output_dir: str) -> str:
        """
        Constructs the standard 'output1 (ID).ogg' path.

        Args:
            filename: The source filename (e.g., "output1 (123).wav").
            output_dir: The target directory.

        Returns:
            The full path for the 'output1' file.
        """
        base_name_match = os.path.splitext(filename)[0]
        if base_name_match.startswith("output1 "):
            base_name = base_name_match[8:]
        else:
            base_name = base_name_match

        output_file_name = f"output1 {base_name}.ogg"
        output_path_ogg = os.path.join(output_dir, output_file_name)
        return output_path_ogg
