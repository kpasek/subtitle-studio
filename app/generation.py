from tkinter import messagebox
from typing import List, Dict
from audio.generation_manager import GenerationManager, GenerationJob, ConversionJob
from pathlib import Path
from app.utils import ready_dir_from_audio_dir
from app.entity import Line
from app.io import get_primary_audio_path
import os


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



def enqueue_generate_all(app):
    # Check for active job first
    manager = GenerationManager.get_instance()
    if manager.is_busy():
        from ui.generation_summary import GenerationSummaryWindow
        GenerationSummaryWindow(
            app,
            "Postęp (zadanie w tle)",
            0, 0, None, monitor_only=True
        )
        return

    if not prepare_job_dependencies(app):
        return

    lines: LineList = app.lines
    total_items = len(lines)
    existing_items = 0
    error_items = 0

    for i, line in enumerate(lines):
        uid = line.uid
        if getattr(line, 'status_flag', None) == "ERROR":
            error_items += 1
            
        existing_audio = get_primary_audio_path(uid)
        if existing_audio and existing_audio.exists():
            existing_items += 1

    from ui.generation_summary import GenerationSummaryWindow
    GenerationSummaryWindow(
        app,
        "Generowanie dialogów",
        total_items,
        existing_items,
        callback=lambda overwrite, only_errors: _execute_generate_all(app, overwrite, only_errors),
        error_count=error_items
    )


def _execute_generate_all(app, overwrite: bool, only_errors: bool = False):
    # Fix: Get model name from project config directly
    tts_model = app.project_config.get('active_tts_model')
    if not tts_model:
        return False

    dialogs_to_generate = []

    uid_to_idx: Dict[str, int] = {}
    lines: LineList = app.lines
    for i, line in enumerate(lines):
        # SKIP if DONE
        if getattr(line, 'status_flag', None) == "DONE":
            continue
            
        # If filtering by errors
        if only_errors and getattr(line, 'status_flag', None) != "ERROR":
             continue

        uid = line.uid
        text = line.get_tts_text().strip()

        if not text:
            continue

        if not overwrite and not only_errors:
            # Check existing only if NOT overwriting AND NOT explicitly regenerating errors
            # if only_errors is True, we regenerate even if exists (it's flagged error after all)
            existing_audio = get_primary_audio_path(uid)
            if existing_audio and existing_audio.exists():
                 continue

        dialogs_to_generate.append((uid, text))
        uid_to_idx[uid] = i

    if not dialogs_to_generate:
        messagebox.showinfo("Info", "Brak dialogów do wygenerowania, które spełniają kryteria.")
        return False

    def _on_generate(identifier: str, path: str):
        try:
            target_idx = uid_to_idx.get(identifier)
            if target_idx is None:
                target_idx = next((i for i, l in enumerate(lines) if l.uid == identifier), None)
            if target_idx is not None and 0 <= target_idx < len(lines):
                line_obj = lines[target_idx]
                line_obj.audio_filename = Path(path).name
                line_obj.audio_status = 'OK' # Resetujemy status na OK (bo nowy plik)
                # Czyścimy dane weryfikacji
                line_obj.audio_similarity = 0.0
                line_obj.audio_hallucination = "PENDING"
                # Jeśli była flaga ERROR, można ją zdjąć? 
                # User did not explicit say to clear ERROR flag on success. 
                # "Generowanie dialogów ma od razu usuwać dane o weryfikacji"
                # Maybe leave flag manual? safer.
                
                # Zapisujemy
                try:
                    # dummy save or rely on bulk save later? 
                    # Generation usually saves automatically via app state
                    pass
                except: 
                    pass
        except Exception as e:
            print(f"Error update line: {e}")
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
    # show_generation_queue(app) # Moved to dedicated window progress
    app.set_status(f"Dodano {len(dialogs_to_generate)} linii do kolejki.")
    return True


def enqueue_convert_all(app):
    # Check for active job first
    manager = GenerationManager.get_instance()
    if manager.is_busy():
        from ui.generation_summary import GenerationSummaryWindow
        GenerationSummaryWindow(
            app,
            "Postęp (zadanie w tle)",
            0, 0, None, monitor_only=True
        )
        return

    if not app.audio_dir or not app.audio_dir.is_dir():
        messagebox.showwarning("Brak katalogu", "Najpierw wybierz katalog audio.", parent=app)
        return

    source_files = list(app.audio_dir.glob("output1 (*).wav")) + list(app.audio_dir.glob("output1 (*).mp3"))
    total_source = len(source_files)

    if total_source == 0:
        messagebox.showinfo("Informacja", "Brak plików źródłowych (output1_*.wav/mp3) do konwersji.", parent=app)
        return

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
        callback=lambda overwrite, only_errors=False: _execute_convert_all(app, overwrite)
    )


def _execute_convert_all(app, overwrite: bool):
    if overwrite:
        ready_dir = ready_dir_from_audio_dir(app.audio_dir)
        if ready_dir.exists():
            try:
                for f in ready_dir.glob("*.ogg"):
                    os.remove(f)
                for f in ready_dir.glob("*.mp3"):
                    os.remove(f)
            except Exception as e:
                print(f"Błąd czyszczenia katalogu ready: {e}")

    if not app.current_project_path:
        messagebox.showwarning("Brak projektu", "Zapisz projekt przed dodaniem do kolejki.", parent=app)
        return False

    job = ConversionJob(
        project_path=f"KONWERSJA - {app.current_project_path.name}",
        audio_dir=app.audio_dir,
        converter_config=app._gather_converter_config()
    )
    GenerationManager.get_instance().add_job(job)
    app.set_status("Dodano zadanie konwersji audio do kolejki.")
    return True
