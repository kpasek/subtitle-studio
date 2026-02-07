from tkinter import messagebox
from typing import List, Tuple, Dict
from audio.generation_manager import GenerationManager, GenerationJob, ConversionJob
from pathlib import Path
from app.utils import ready_dir_from_audio_dir
from app.entity import Line
import os
import json


LineList = List[Line]


def prepare_job_dependencies(app) -> bool:
    lines: LineList = app.lines
    if not app.audio_dir or not app.audio_dir.is_dir():
        messagebox.showwarning("Brak katalogu", "Najpierw wybierz katalog audio.", parent=app)
        return False
    if not app.current_project_path:
        messagebox.showwarning("Brak projektu", "Zapisz projekt przed dodaniem do kolejki.", parent=app)
        return False
    if not lines:
        messagebox.showwarning("Brak danych", "Najpierw przetwórz napisy.", parent=app)
        return False
    return True


def _normalize_uid(uid: str) -> str:
    """Konwertuje sam UUID na pełną nazwę pliku output1 (uid)"""
    if uid.startswith("output1 ("):
        return uid
    return f"output1 ({uid})"


def _audio_path(audio_dir: Path, uid: str, ext: str) -> Path:
    """Konstruuje pełną ścieżkę do pliku audio na podstawie uid"""
    return audio_dir / f"{_normalize_uid(uid)}.{ext}"




def enqueue_generate_all(app):
    if not prepare_job_dependencies(app):
        return

    lines: LineList = app.lines
    total_items = len(lines)
    existing_items = 0

    for i, line in enumerate(lines):
        uid = line.uid
        raw_wav = _audio_path(app.audio_dir, uid, 'wav')
        raw_mp3 = _audio_path(app.audio_dir, uid, 'mp3')
        if raw_wav.exists() or raw_mp3.exists():
            existing_items += 1

    from ui.generation_summary import GenerationSummaryWindow
    GenerationSummaryWindow(
        app,
        "Generowanie dialogów",
        total_items,
        existing_items,
        callback=lambda overwrite: _execute_generate_all(app, overwrite)
    )


def _execute_generate_all(app, overwrite: bool):
    tts_model = app._get_active_tts_model_name()
    if not tts_model:
        return

    dialogs_to_generate = []

    uid_to_idx: Dict[str, int] = {}
    lines: LineList = app.lines
    for i, line in enumerate(lines):
        uid = line.uid
        text = line.get_tts_text().strip()

        if not text:
            continue

        if not overwrite:
            raw_wav = _audio_path(app.audio_dir, uid, 'wav')
            raw_mp3 = _audio_path(app.audio_dir, uid, 'mp3')
            if raw_wav.exists() or raw_mp3.exists():
                continue
        dialogs_to_generate.append((uid, text))
        uid_to_idx[uid] = i

    if not dialogs_to_generate:
        messagebox.showinfo("Info", "Brak dialogów do wygenerowania (wszystkie istnieją lub są puste).")
        return

    def _on_generate(identifier: str, path: str):
        try:
            target_idx = uid_to_idx.get(identifier)
            if target_idx is None:
                target_idx = next((i for i, l in enumerate(lines) if l.uid == identifier), None)
            if target_idx is not None and 0 <= target_idx < len(lines):
                lines[target_idx].audio_filename = Path(path).name
                lines[target_idx].audio_status = 'OK'
            try:
                from app.io import save_lines_to_file
                if getattr(app, 'loaded_path', None):
                    save_lines_to_file(str(app.loaded_path), lines)
            except Exception:
                pass
        except Exception:
            pass

    job = GenerationJob(
        project_path=app.current_project_path.name,
        audio_dir=app.audio_dir,
        lines_to_generate=dialogs_to_generate,
        tts_model_name=tts_model,
        tts_config=app._gather_tts_config(),
        converter_config=app._gather_converter_config()
    )
    job.on_generate = _on_generate
    GenerationManager.get_instance().add_job(job)
    app.show_generation_queue()
    app.set_status(f"Dodano {len(dialogs_to_generate)} linii do kolejki.")


def enqueue_convert_all(app):
    if not app.audio_dir or not app.audio_dir.is_dir():
        messagebox.showwarning("Brak katalogu", "Najpierw wybierz katalog audio.", parent=app)
        return

    source_files = list(app.audio_dir.glob("output1 (*).wav")) + list(app.audio_dir.glob("output1 (*).mp3"))
    total_source = len(source_files)

    ready_dir = ready_dir_from_audio_dir(app.audio_dir)
    existing_target = 0
    if ready_dir.exists():
        existing_target = len(list(ready_dir.glob("*.ogg"))) + len(list(ready_dir.glob("*.mp3")))

    from ui.generation_summary import GenerationSummaryWindow
    GenerationSummaryWindow(
        app,
        "Konwersja audio",
        total_source,
        existing_target,
        callback=lambda overwrite: _execute_convert_all(app, overwrite)
    )


def _execute_convert_all(app, overwrite: bool):
    if overwrite:
        ready_dir = ready_dir_from_audio_dir(app.audio_dir)
        if ready_dir.exists():
            try:
                for f in ready_dir.glob("*.ogg"):
                    os.remove(f)
            except Exception as e:
                print(f"Błąd czyszczenia katalogu ready: {e}")

    if os.name == 'nt':
        converter_config = app._gather_converter_config()
        workers = converter_config.get("conversion_workers", 4)
        filters = converter_config.get("ffmpeg_filters", {})
        fmt = converter_config.get("audio_output_format", "ogg")

        if getattr(__import__('sys'), 'frozen', False):
            exe_path = "converter.exe"
        else:
            exe_path = str(Path(__file__).parent.parent / "audio" / "converter.py")

        cmd = [
            exe_path,
            "--path", str(app.audio_dir),
            "--workers", str(workers),
            "--format", fmt,
            "--filters", json.dumps(filters)
        ]
        if not getattr(__import__('sys'), 'frozen', False):
            cmd.insert(0, __import__('sys').executable)

        try:
            creation_flags = __import__('subprocess').CREATE_NEW_CONSOLE
            __import__('subprocess').Popen(cmd, creationflags=creation_flags)
            app.set_status("Rozpoczęto konwersję w nowym procesie.")
        except Exception as e:
            messagebox.showerror("Błąd uruchamiania konwersji", str(e), parent=app)
    else:
        if not app.current_project_path:
            messagebox.showwarning("Brak projektu", "Zapisz projekt przed dodaniem do kolejki.", parent=app)
            return
        job = ConversionJob(
            project_path=f"KONWERSJA - {app.current_project_path.name}",
            audio_dir=app.audio_dir,
            converter_config=app._gather_converter_config()
        )
        GenerationManager.get_instance().add_job(job)
        app.show_generation_queue()
        app.set_status("Dodano zadanie konwersji audio do kolejki.")
