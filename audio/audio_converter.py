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
    input_file, output_file, base_speed, filter_settings = task_args

    print(f"[Worker] Przetwarzam: {input_file} -> {output_file}")

    try:
        converter_instance = AudioConverter(
            base_speed=base_speed, filter_settings=filter_settings)
        converter_instance.parse_ogg(input_file, output_file)
        return (input_file, True, None)
    except Exception as e:
        print(f"[Worker] Błąd podczas przetwarzania {input_file}: {e}")
        return (input_file, False, str(e))


class AudioConverter:
    """
    Handles audio conversion, applying speed changes and FFmpeg filters.
    """

    def __init__(self, base_speed: float = 1.1, filter_settings: Optional[Dict[str, Any]] = None):
        """
        Initializes the converter.

        Args:
            base_speed: The base speed multiplier for audio (e.g., 1.1).
            filter_settings: A dictionary of filter configurations from global settings.
        """
        self.base_speed = base_speed
        self.filter_settings = filter_settings if filter_settings is not None else {}

    def calculate_base_speed(self, duration_ms: float) -> float:
        """
        Calculates a dynamic speed multiplier based on audio duration.
        Longer files are sped up slightly more.

        Args:
            duration_ms: The duration of the audio in milliseconds.

        Returns:
            The calculated speed multiplier.
        """
        duration_sec = duration_ms / 1000
        if duration_sec < 2:
            return 1.0

        if duration_sec <= 3:
            return self.base_speed
        extra_time = duration_sec - 3
        multiplier = (0.02 * math.ceil(extra_time / 2))
        speed_factor = self.base_speed + multiplier
        return min(speed_factor, self.base_speed * 1.2)

    def parse_ogg(self, input_file: str, output_file: str):
        """
        Converts a single audio file (.wav, .mp3, .ogg) to two .ogg files
        in the /ready/ directory (output1 and output2) with filters applied.

        Args:
            input_file: Path to the source audio file.
            output_file: Path for the 'output1' (base speed) .ogg file.
        """

        input_filename = os.path.basename(input_file)
        input_dir = os.path.dirname(output_file)

        base_name_match = os.path.splitext(input_filename)[0]
        if base_name_match.startswith("output1 "):
            base_name = base_name_match[8:]
        else:
            base_name = base_name_match

        output_path_speed = os.path.join(
            input_dir, f"output2 {base_name}.ogg")

        if os.path.exists(output_path_speed) and os.path.exists(output_file):
            return

        try:
            if input_file.lower().endswith('.ogg'):
                audio = AudioSegment.from_ogg(input_file)
            elif input_file.lower().endswith('.mp3'):
                audio = AudioSegment.from_mp3(input_file)
            else:
                audio = AudioSegment.from_wav(input_file)

            base_speed = self.calculate_base_speed(len(audio))

            if not os.path.exists(output_file):
                self.export_file(audio, output_file, base_speed)

            if not os.path.exists(output_path_speed):
                speed = 1.10 if (len(audio) / 1000) > 2 else 1
                self.export_file(audio, output_path_speed, base_speed * speed)

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

    def export_file(self, audio: AudioSegment, output_file: str, speed: float):
        """
        Exports an AudioSegment to a temporary .ogg file, then runs FFmpeg
        to apply filters and speed changes, saving the final .ogg file.

        Args:
            audio: The Pydub AudioSegment.
            output_file: The final destination path for the .ogg file.
            speed: The speed multiplier (atempo) to apply.
        """
        temp_file = output_file + ".temp.ogg"
        audio.export(temp_file, format="ogg")

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
        speed_filter = f"atempo={speed}" if speed != 1.0 else ""

        if filter_str and speed_filter:
            final_filter_chain = f"{filter_str},{speed_filter}"
        elif filter_str:
            final_filter_chain = filter_str
        elif speed_filter:
            final_filter_chain = speed_filter
        else:
            final_filter_chain = ""

        # Zamiast tworzyć string, tworzymy listę argumentów
        command_list = [
            'ffmpeg',
            '-i', temp_file
        ]

        if final_filter_chain:
            command_list.extend(['-af', final_filter_chain])
            command_list.extend(['-c:a', 'libvorbis'])
        else:
            # Jeśli nie ma filtrów ani zmiany prędkości, kopiuj strumień
            command_list.extend(['-c', 'copy'])

        command_list.extend([
            '-y',
            '-loglevel', 'error',
            output_file
        ])

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW

        try:
            # Wywołujemy polecenie z `shell=False` (domyślne)
            # przekazując listę argumentów `command_list`.
            # Teraz flaga `creation_flags` będzie poprawnie zastosowana
            # do procesu `ffmpeg.exe`, ukrywając jego okno.
            result = subprocess.run(
                command_list,
                shell=False,  # Kluczowa zmiana!
                check=True,
                creationflags=creation_flags,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
        except subprocess.CalledProcessError as e:
            print(f"Błąd FFmpeg (stdout): {e.stdout}")
            print(f"Błąd FFmpeg (stderr): {e.stderr}")
            raise Exception(f"Błąd FFmpeg: {e.stderr}")
        except Exception as e:
            print(f"Nieoczekiwany błąd subprocess: {e}")
            raise e

        try:
            os.remove(temp_file)
        except Exception as e:
            print(
                f"Ostrzeżenie: Nie udało się usunąć pliku tymczasowego {temp_file}: {e}")

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
                output_path_speed = os.path.join(
                    output_dir, f"output2 {base_name}.ogg")

                if os.path.exists(output_path_ogg) and os.path.exists(output_path_speed):
                    continue

                task_args = (input_path, output_path_ogg,
                             self.base_speed, self.filter_settings)
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
