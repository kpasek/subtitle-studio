from tkinter import messagebox
from typing import Optional, List, Tuple
from audio.generation_manager import GenerationManager, GenerationJob, ConversionJob
from pathlib import Path
import os
import json


def prepare_job_dependencies(app) -> bool:
    if not app.audio_dir or not app.audio_dir.is_dir():
        messagebox.showwarning("Brak katalogu", "Najpierw wybierz katalog audio.", parent=app)
        return False
    if not app.current_project_path:
        messagebox.showwarning("Brak projektu", "Zapisz projekt przed dodaniem do kolejki.", parent=app)
        return False
    if not app.lines:
        messagebox.showwarning("Brak danych", "Najpierw przetwórz napisy.", parent=app)
        return False
    return True


def enqueue_generate_single(app, line_no: Optional[int] = None):
    if not prepare_job_dependencies(app):
        return
    if line_no is None:
        if app.selected_line_index is None:
            messagebox.showwarning("Brak zaznaczenia", "Najpierw wybierz linię.", parent=app)
            return
        line_no = int(app.selected_line_index + 1)

    identifier = (line_no - 1)
    try:
        text = app.lines[identifier].tts_text
        lines_to_gen = [(str(line_no), text)]
    except (IndexError, ValueError):
        return

    tts_model = app._get_active_tts_model_name()
    if not tts_model:
        messagebox.showerror("Błąd", "Brak modelu TTS.")
        return

    job = GenerationJob(
        project_path=f"POJEDYNCZY ({line_no}) - {app.current_project_path.name}",
        audio_dir=app.audio_dir,
        lines_to_generate=lines_to_gen,
        tts_model_name=tts_model,
        tts_config=app._gather_tts_config(),
        converter_config=app._gather_converter_config()
    )
    # notify app after each generated file so UI/model can be updated
    def _on_generate(identifier: str, path: str):
        try:
            idx = int(identifier) - 1
            if 0 <= idx < len(app.lines):
                app.lines[idx].audio_filename = Path(path).name
                app.lines[idx].audio_status = 'OK'
                # try to probe duration via ffprobe
                try:
                    from app.subtitles import SubtitlePanel
                    # best-effort: leave duration to verification or external probe
                except Exception:
                    pass
                # persist csv
                try:
                    from app.io import save_lines_to_file
                    if getattr(app, 'loaded_path', None):
                        save_lines_to_file(str(app.loaded_path), app.lines)
                except Exception:
                    pass
        except Exception:
            pass
    job.on_generate = _on_generate
    GenerationManager.get_instance().add_job(job)
    app.set_status(f"Dodano zadanie (linia {line_no}) do kolejki.")


def enqueue_generate_all(app):
    if not prepare_job_dependencies(app):
        return

    total_items = len(app.lines)
    existing_items = 0

    for i in range(total_items):
        identifier = str(i + 1)
        raw_wav = app.audio_dir / f"output1 ({identifier}).wav"
        raw_mp3 = app.audio_dir / f"output1 ({identifier}).mp3"
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

    for i, line in enumerate(app.lines):
        identifier = str(i + 1)
        text = line.tts_text.strip()

        if not text:
            continue

        if not overwrite:
            raw_wav = app.audio_dir / f"output1 ({identifier}).wav"
            raw_mp3 = app.audio_dir / f"output1 ({identifier}).mp3"
            if raw_wav.exists() or raw_mp3.exists():
                continue

        dialogs_to_generate.append((identifier, text))

    if not dialogs_to_generate:
        messagebox.showinfo("Info", "Brak dialogów do wygenerowania (wszystkie istnieją lub są puste).")
        return

    job = GenerationJob(
        project_path=app.current_project_path.name,
        audio_dir=app.audio_dir,
        lines_to_generate=dialogs_to_generate,
        tts_model_name=tts_model,
        tts_config=app._gather_tts_config(),
        converter_config=app._gather_converter_config()
    )
    def _on_generate(identifier: str, path: str):
        try:
            idx = int(identifier) - 1
            if 0 <= idx < len(app.lines):
                app.lines[idx].audio_filename = Path(path).name
                app.lines[idx].audio_status = 'OK'
                try:
                    from app.io import save_lines_to_file
                    if getattr(app, 'loaded_path', None):
                        save_lines_to_file(str(app.loaded_path), app.lines)
                except Exception:
                    pass
        except Exception:
            pass
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

    ready_dir = app.audio_dir / "ready"
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
        ready_dir = app.audio_dir / "ready"
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
