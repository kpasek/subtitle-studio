import json
import os
import datetime
from pathlib import Path
from typing import Optional, List
from tkinter import filedialog, messagebox, TclError, simpledialog

from app.utils import ensure_project_dirs, project_generated_dir, project_ready_dir, project_subtitles_dir
from app.entity import Line, PatternItem
from app.io import load_subtitle_file, save_lines_to_file, APP_CONFIG


def create_new_project(app):
    """Tworzy nową strukturę projektu w wybranym folderze."""
    if not _check_unsaved_changes(app):
        return

    # 1. Wybierz katalog nadrzędny projektu
    initial_dir = app.global_config.get('start_directory') or str(Path.cwd())
    project_dir = filedialog.askdirectory(title="Wybierz folder bazowy dla projektu", initialdir=initial_dir)
    if not project_dir:
        return

    # 2. Podaj nazwę projektu
    project_name = simpledialog.askstring("Nowy projekt", "Podaj nazwę projektu (nazwa pliku json):")
    if not project_name:
        return

    if not project_name.lower().endswith(".json"):
        project_name += ".json"

    project_path = Path(project_dir) / project_name

    if project_path.exists():
        if not messagebox.askyesno("Projekt istnieje", f"Plik {project_name} już istnieje. Nadpisać?"):
            return

    # 3. Stwórz strukturę katalogów
    ensure_project_dirs(project_path)

    # 4. Stwórz pusty plik projektu z domyślną konfiguracją
    default_cfg = {
        "builtin_remove_state": [True] * len(app.builtin_remove_state),
        "builtin_replace_state": [True] * len(app.builtin_replace_state),
        "custom_remove": [],
        "custom_replace": [],
        "subtitle_path": None,
        "audio_path": str(project_generated_dir(project_path).absolute()),
        "active_tts_model": "XTTS",
        "base_audio_speed": 1.1
    }

    try:
        with open(project_path, "w", encoding="utf-8") as f:
            json.dump(default_cfg, f, indent=2, ensure_ascii=False)

        # 5. Otwórz nowy projekt
        open_project(app, str(project_path))
    except Exception as e:
        messagebox.showerror("Błąd", f"Nie udało się stworzyć projektu:\n{e}")


def import_old_project(app):
    """Importuje stary projekt i dostosowuje do nowej struktury (UID na podstawie nr linii)."""
    if not _check_unsaved_changes(app):
        return

    initial_dir = app.global_config.get('start_directory') or str(Path.cwd())
    path = filedialog.askopenfilename(title="Wybierz stary projekt (.json) do importu",
                                      filetypes=[("JSON", "*.json")],
                                      initialdir=initial_dir)
    if not path:
        return

    try:
        open_project(app, path)
        project_path = Path(path)
        project_root = project_path.parent

        # 1. Obsługa starych ścieżek audio
        old_audio_path_str = app.project_config.get("audio_path")
        if old_audio_path_str:
            old_audio_path = Path(old_audio_path_str)
            new_gen_dir = project_generated_dir(project_path)
            new_ready_dir = project_ready_dir(project_path)

            if old_audio_path.exists() and old_audio_path.resolve() != new_gen_dir.resolve():
                import shutil
                # Przenieś pliki z starego katalogu audio do generated/
                for item in old_audio_path.iterdir():
                    if item.is_file():
                        shutil.move(str(item), str(new_gen_dir / item.name))
                    elif item.is_dir() and item.name == "ready":
                        # Przenieś zawartość starego ready do nowego ready/
                        for ready_item in item.iterdir():
                            if ready_item.is_file():
                                shutil.move(str(ready_item), str(new_ready_dir / ready_item.name))
                
                # Zaktualizuj ścieżkę w konfiguracji projektu
                app.project_config["audio_path"] = str(new_gen_dir.absolute())

        # 2. Przypisanie UID na podstawie numeru linii
        if app.lines:
            import shutil
            for i, line in enumerate(app.lines, start=1):
                old_uid = line.uid
                new_uid = str(i)
                
                # Jeśli importujemy projekt, a pliki mają już zapisaną UID,
                # musimy zmienić ich nazwy, aby pasowały do nowych UID (numerów linii).
                if old_uid and old_uid != new_uid and app.audio_dir:
                    for ext in ['.wav', '.mp3', '.ogg']:
                        # Konwencje nazw: "output1 (uid).ext"
                        old_file = app.audio_dir / f"output1 ({old_uid}){ext}"
                        if old_file.exists():
                            new_file = app.audio_dir / f"output1 ({new_uid}){ext}"
                            try:
                                if not new_file.exists():
                                    shutil.move(str(old_file), str(new_file))
                                else:
                                    # Jeśli plik docelowy istnieje, usuwamy stary (zakładamy migrację)
                                    old_file.unlink()
                            except Exception as e:
                                print(f"Błąd zmiany nazwy pliku audio {old_file.name}: {e}")
                        
                        # Sprawdź pliki w ready/ (jeśli istnieją)
                        ready_dir = project_ready_dir(project_path)
                        old_ready = ready_dir / f"output1 ({old_uid}){ext}"
                        if old_ready.exists():
                            new_ready = ready_dir / f"output1 ({new_uid}){ext}"
                            try:
                                if not new_ready.exists():
                                    shutil.move(str(old_ready), str(new_ready))
                                else:
                                    old_ready.unlink()
                            except Exception as e:
                                print(f"Błąd zmiany nazwy w ready/ {old_ready.name}: {e}")

                line.uid = new_uid
                # Czyścimy starą nazwę pliku - teraz pole polega wyłącznie na UID
                line.audio_filename = ""

            line_count = len(app.lines)

            # Skorzystaj z logiki "Zatwierdź zmiany", aby przenieść plik do /subtitles i zaktualizować projekt
            # Ważne: UID muszą być ustawione ZANIM wywołamy _finalize_processing
            from app.patterns import _finalize_processing
            _finalize_processing(app, remove_empty=False, remove_duplicates=False)

            msg = f"Import zakończony powodzeniem, zaimportowano {line_count} wierszy oraz {line_count} dialogów."
            messagebox.showinfo("Import", msg)
    except Exception as e:
        messagebox.showerror("Błąd importu", f"Nie udało się zaimportować projektu:\n{e}")


def open_project(app, path: Optional[str] = None):
    """Otwiera plik projektu .json."""
    if path is None:
        if not _check_unsaved_changes(app):
            return
        initial_dir = app.global_config.get('start_directory') or str(Path.cwd())
        path = filedialog.askopenfilename(title="Otwórz projekt",
                                          filetypes=[("JSON", "*.json"), ("All", "*")],
                                          initialdir=initial_dir)
    if not path:
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        app.current_project_path = Path(path)
        _set_project_audio_state(app)
        app.project_config = cfg

        _update_recent_projects(app, str(app.current_project_path))

        all_vars = app.builtin_remove_state + app.builtin_replace_state
        for var in all_vars:
            for mode_info, trace_id in var.trace_info():
                if "write" in mode_info:
                    try:
                        var.trace_remove("write", trace_id)
                    except TclError:
                        pass

        for i, val in enumerate(cfg.get("builtin_remove_state", [])):
            if i < len(app.builtin_remove_state):
                app.builtin_remove_state[i].set(bool(val))
        for i, val in enumerate(cfg.get("builtin_replace_state", [])):
            if i < len(app.builtin_replace_state):
                app.builtin_replace_state[i].set(bool(val))

        for var in all_vars:
            var.trace_add("write", app.mark_as_unsaved)

        app.custom_remove = [PatternItem.from_json(x) for x in cfg.get("custom_remove", [])]
        app.custom_replace = [PatternItem.from_json(x) for x in cfg.get("custom_replace", [])]
        
        # Reset edycji ręcznych przy otwieraniu/tworzeniu projektu
        app.manual_edits = {}
        app.tts_edits = {}
        
        app._refresh_custom_lists()

        # Wczytaj audio_path PIERWSZY - potrzebny dla kompatybilności wstecznej txt
        audio_path_str = cfg.get("audio_path")
        subtitle_path = cfg.get("subtitle_path")
        if subtitle_path and Path(subtitle_path).exists():
            # Load subtitles via central IO helper to ensure audio metadata is populated
            try:
                from app.io import load_subtitle_file, save_lines_to_file
                subtitle_path_obj = Path(subtitle_path)
                # Jeśli to txt, przesłaj audio_dir dla kompatybilności wstecznej
                audio_dir_for_compat = app.audio_dir if subtitle_path_obj.suffix.lower() == '.txt' else None
                loaded = load_subtitle_file(subtitle_path, audio_dir=audio_dir_for_compat)
                app.lines = loaded
                app.loaded_path = subtitle_path_obj
                if subtitle_path_obj.suffix.lower() == '.txt':
                    csv_candidate = subtitle_path_obj.with_suffix('.csv')
                    if not csv_candidate.exists():
                        try:
                            save_lines_to_file(str(csv_candidate), loaded)
                        except Exception as write_err:
                            print(f"Błąd zapisu CSV po imporcie TXT: {write_err}")
                    if csv_candidate.exists():
                        app.loaded_path = csv_candidate

                # apply patterns and initialize subtitle panel state
                try:
                    app.apply_patterns()
                except Exception:
                    pass
        
            except Exception as e:
                print(f"Błąd wczytywania napisów z projektu: {e}")
                app.lines = []
        else:
            app.lines = []
            app.loaded_path = None
            app.apply_patterns()
            # Wymuś odświeżenie panelu, gdy lista jest pusta
            if hasattr(app, '_update_subtitle_panel_content'):
                app._update_subtitle_panel_content()
            
            if app.lbl_filename:
                app.lbl_filename.configure(text="Brak wczytanego pliku")

        app.set_status(f"Wczytano projekt: {app.current_project_path.name}")
        app.save_app_setting('last_project', path)
        app.has_unsaved_changes = False
        if app.lbl_filename:
            app.lbl_filename.configure(text=os.path.basename(path))

        app.subtitle_panel.update_audio_buttons_state()

    except Exception as e:
        messagebox.showerror("Błąd wczytywania projektu", f"Nie udało się wczytać konfiguracji:\n{e}")
        app.current_project_path = None
        app.project_config = {}
        app.has_unsaved_changes = False
    app._refresh_custom_lists()


def close_project(app):
    """Zamyka obecny projekt (restartuje apkę)."""
    if not _check_unsaved_changes(app):
        return
    try:
        app.save_app_setting('last_project', None)
        os.execl(__import__('sys').executable, __import__('sys').executable, *__import__('sys').argv)
    except Exception as e:
        messagebox.showerror("Błąd restartu", f"Nie udało się zrestartować aplikacji:\n{e}")


def save_project(app, cfg: dict | None = None):
    if not app.current_project_path:
        return save_project_as(app)
    final_cfg = _gather_project_config(app)
    if cfg:
        final_cfg.update(cfg)
    app.project_config = final_cfg
    try:
        with open(app.current_project_path, "w", encoding="utf-8") as f:
            json.dump(final_cfg, f, indent=2, ensure_ascii=False)
        app.set_status(f"Zapisano projekt: {app.current_project_path.name}")
        app.has_unsaved_changes = False
    except Exception as e:
        messagebox.showerror("Błąd", f"Nie udało się zapisać konfiguracji:\n{e}")


def save_project_as(app):
    path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")],
                                        initialdir=app.global_config.get('start_directory'))
    if not path:
        return
    app.current_project_path = Path(path)
    _set_project_audio_state(app)
    save_project(app)


def set_project_config(app, param, value):
    if app.project_config is None:
        app.project_config = {}
    if app.project_config.get(param) != value:
        app.project_config[param] = value
        app.mark_as_unsaved()
        if app.current_project_path:
            save_project(app)


def _gather_project_config(app) -> dict:
    current_cfg = app.project_config.copy() if app.project_config else {}
    current_cfg.update({
        "builtin_remove_state": [bool(v.get()) for v in app.builtin_remove_state],
        "builtin_replace_state": [bool(v.get()) for v in app.builtin_replace_state],
        "custom_remove": [p.to_json() for p in app.custom_remove],
        "custom_replace": [p.to_json() for p in app.custom_replace],
        "subtitle_path": str(app.loaded_path) if app.loaded_path else None,
        "audio_path": str(project_generated_dir(app.current_project_path).absolute()) if app.current_project_path else None,
        "active_tts_model": app.project_config.get('active_tts_model', 'XTTS'),
        "base_audio_speed": app.project_config.get('base_audio_speed', 1.1)
    })
    return current_cfg


def _load_app_config(app, only_config=False):
    if os.path.exists(APP_CONFIG):
        try:
            with open(APP_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            app.global_config = cfg
        except Exception as e:
            print(f"Błąd wczytywania configu: {e}")
            app.global_config = {}
    else:
        app.global_config = {}


def save_app_setting(app, param, value):
    app.global_config.update({param: value})
    try:
        with open(APP_CONFIG, "w", encoding="utf-8") as f:
            json.dump(app.global_config, f, indent=2)
    except Exception:
        pass


def save_global_config(app, data: dict):
    for key, value in data.items():
        app.global_config[key] = value

    try:
        with open(APP_CONFIG, "w", encoding="utf-8") as f:
            json.dump(app.global_config, f, indent=4)
        app.set_status("Zapisano ustawienia aplikacji.")
        app.apply_theme_settings()
    except Exception as e:
        messagebox.showerror("Błąd", f"Nie udało się zapisać ustawień:\n{e}")


def _check_unsaved_changes(app) -> bool:
    if app.has_unsaved_changes and app.current_project_path:
        msg = "Masz niezapisane zmiany w projekcie. Czy chcesz je zapisać?"
        result = messagebox.askyesnocancel("Niezapisane zmiany", msg, parent=app)
        if result is True:
            save_project(app)
        elif result is None:
            return False
    return True


def _set_project_audio_state(app):
    if not app.current_project_path:
        app.audio_dir = None
        return
    ensure_project_dirs(app.current_project_path)
    app.audio_dir = project_generated_dir(app.current_project_path)
    panel = getattr(app, 'subtitle_panel', None)
    if panel:
        panel.update_audio_buttons_state()


def _update_recent_projects(app, path: str):
    recents = app.global_config.get('recent_projects', [])
    if path in recents:
        recents.remove(path)
    recents.insert(0, path)
    recents = recents[:15]
    save_app_setting(app, 'recent_projects', recents)


def open_recent_projects_window(app):
    recents = app.global_config.get('recent_projects', [])
    from ui.recent_projects import RecentProjectsWindow
    RecentProjectsWindow(
        app,
        recents,
        on_open_callback=open_project,
        on_delete_callback=_remove_recent_project,
        on_clear_callback=_clear_recent_projects
    )


def _remove_recent_project(app, path: str):
    recents = app.global_config.get('recent_projects', [])
    if path in recents:
        recents.remove(path)
        save_app_setting(app, 'recent_projects', recents)


def _clear_recent_projects(app):
    save_app_setting(app, 'recent_projects', [])


def add_new_subtitles(app):
    """Dodaje nowe wiersze do pliku CSV. Może załadować z istniejącego CSV lub pliku TXT."""
    # Pytanie czy załadować z CSV czy TXT
    choice = messagebox.askyesno(
        "Dodaj napisy",
        "Czy załadować z pliku?\n\nTAK  - wybierz plik CSV lub TXT\nNIE - dodaj puste wiersze",
        parent=app
    )

    new_lines_to_add: List[Line] = []

    if choice:
        # Użytkownik wybrał załadowanie z pliku
        init_dir = app.global_config.get('start_directory')
        file_path = filedialog.askopenfilename(
            title="Wybierz plik CSV lub TXT z napisami",
            filetypes=[('CSV files', '*.csv'), ('Text files', '*.txt'), ('All files', '*.*')],
            initialdir=init_dir,
            parent=app
        )

        if not file_path:
            return

        file_path = Path(file_path)

        # Wczytaj plik za pośrednictwem load_subtitle_file
        try:
            # Jeśli to TXT, przesłaj audio_dir dla kompatybilności wstecznej
            audio_dir_for_compat = app.audio_dir if file_path.suffix.lower() == '.txt' else None
            new_lines_to_add = load_subtitle_file(str(file_path), audio_dir=audio_dir_for_compat)

            if not new_lines_to_add:
                messagebox.showwarning('Brak danych', 'Plik nie zawiera żadnych danych.', parent=app)
                return

            target_csv = file_path
            if file_path.suffix.lower() == '.txt':
                csv_candidate = file_path.with_suffix('.csv')
                if not csv_candidate.exists():
                    try:
                        save_lines_to_file(str(csv_candidate), new_lines_to_add)
                    except Exception as write_err:
                        messagebox.showerror('Błąd', f'Nie udało się utworzyć pliku CSV: {write_err}', parent=app)
                        return
                target_csv = csv_candidate

            if target_csv.exists() and not app.loaded_path:
                app.loaded_path = target_csv
                if app.lbl_filename:
                    app.lbl_filename.configure(text=f"Plik: {app.loaded_path.name}")

        except Exception as e:
            messagebox.showerror('Błąd', f'Nie udało się wczytać pliku: {str(e)}', parent=app)
            return
    else:
        # Użytkownik wybrał dodanie ręczne
        num_rows = simpledialog.askinteger(
            "Dodaj napisy",
            "Ile nowych wierszy dodać?",
            parent=app,
            minvalue=1,
            maxvalue=1000,
            initialvalue=10
        )

        if num_rows is None or num_rows <= 0:
            return

        # Utwórz puste wiersze
        for _ in range(num_rows):
            new_line = Line(
                original_text="",
                text="",
                tts_text="",
                audio_duration=0.0,
                audio_filename="",
                audio_similarity=0.0,
                audio_transcribed_text="",
                audio_status="",
                audio_format=""
            )
            new_lines_to_add.append(new_line)

    # Automatycznie stwórz nowy plik CSV jeśli go nie ma
    if not app.loaded_path:
        try:
            # Określ katalog docelowy
            if app.current_project_path:
                target_dir = app.current_project_path.parent / 'subtitles'
                target_dir.mkdir(parents=True, exist_ok=True)
            else:
                start_dir = app.global_config.get('start_directory')
                target_dir = Path(start_dir) if start_dir else Path.home()

            # Utwórz nazwę pliku z timestampem
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            new_csv_filename = f"{timestamp}_subtitles.csv"
            app.loaded_path = target_dir / new_csv_filename

            if app.lbl_filename:
                app.lbl_filename.configure(text=f"Plik: {app.loaded_path.name}")

        except Exception as e:
            messagebox.showerror('Błąd', f'Nie udało się utworzyć ścieżki pliku CSV: {str(e)}', parent=app)
            return

    # Dodaj nowe wiersze do app.lines i zapisz
    try:
        from app.patterns import apply_patterns
        lines = app.lines
        lines.extend(new_lines_to_add)

        # Zapisz do CSV
        save_lines_to_file(str(app.loaded_path), lines)

        # Odświeź UI
        apply_patterns(app)

        num_added = len(new_lines_to_add)
        app.set_status(f"Dodano {num_added} wierszy do {app.loaded_path.name}")
        messagebox.showinfo('Gotowe', f'Dodano {num_added} wierszy do pliku CSV.')
    except Exception as e:
        messagebox.showerror('Błąd', f'Nie udało się dodać wierszy: {str(e)}', parent=app)


def change_subtitle_file(app):
    """Zmienia plik CSV z napisami na inny."""
    from app.patterns import apply_patterns
    # Start in [project_dir]/subtitles if a project is open
    if app.current_project_path:
        init_dir = str(app.current_project_path.parent / 'subtitles')
    else:
        init_dir = app.global_config.get('start_directory')

    path = filedialog.askopenfilename(
        title="Wybierz plik CSV z napisami",
        filetypes=[('CSV', '*.csv'), ('Wszystkie pliki', '*.*')],
        initialdir=init_dir,
        parent=app
    )

    if not path:
        return

    # Sprawdzenie czy plik istnieje
    csv_path = Path(path)
    if not csv_path.exists():
        messagebox.showerror('Błąd', 'Wybrany plik nie istnieje.', parent=app)
        return

    try:
        # Wczytaj nowy plik (uwzglednij kompatybilnosc dla txt)
        audio_dir_for_compat = app.audio_dir if csv_path.suffix.lower() == '.txt' else None
        app.lines = load_subtitle_file(str(csv_path), audio_dir=audio_dir_for_compat)
        app.loaded_path = csv_path

        # Zaktualizuj etykietę z nazwą pliku
        if app.lbl_filename:
            app.lbl_filename.configure(text=f"Plik: {csv_path.name}")

        # Odśwież UI
        apply_patterns(app)

        app.set_status(f"Wczytano: {csv_path.name}")
        messagebox.showinfo('Gotowe', f'Wczytano plik: {csv_path.name}')
    except Exception as e:
        messagebox.showerror('Błąd', f'Nie udało się wczytać pliku: {str(e)}', parent=app)


def download_clean(app):
    lines = app.lines
    if not lines:
        return
    path = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('CSV', '*.csv'), ('Text files', '*.txt')])
    if path:
        if Path(path).suffix.lower() == '.csv':
            save_lines_to_file(path, lines)
        else:
            save_lines_to_file(path, [l.text for l in lines])
        messagebox.showinfo('Gotowe', f'Zapisano: {path}')


def download_replace(app):
    lines = app.lines
    if not lines:
        return
    path = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('CSV', '*.csv'), ('Text files', '*.txt')])
    if path:
        if Path(path).suffix.lower() == '.csv':
            save_lines_to_file(path, lines)
        else:
            save_lines_to_file(path, [l.tts_text for l in lines])
        messagebox.showinfo('Gotowe', f'Zapisano: {path}')


def delete_all_converted_audio(app):
    from app.utils import ready_dir_from_audio_dir
    if not app.audio_dir:
        return messagebox.showwarning("Brak katalogu", "Wybierz katalog audio.", parent=app)
    ready_dir = ready_dir_from_audio_dir(app.audio_dir)
    if not ready_dir.is_dir() or not messagebox.askyesno("Potwierdź", f"Usunąć wszystko z {ready_dir}?"):
        return

    # POPRAWKA: Uwzględnienie zarówno plików .ogg jak i .mp3
    files_to_delete = list(ready_dir.glob('*.ogg')) + list(ready_dir.glob('*.mp3'))

    for f in files_to_delete:
        try:
            os.remove(f)
        except:
            pass
    app.subtitle_panel.update_audio_buttons_state()


def get_active_tts_model_name(app):
    return app.project_config.get('active_tts_model')


def gather_tts_config(app):
    return {
        'local_api_url': app.global_config.get('local_api_url', 'http://127.0.0.1:8001'),
        'xtts_voice_path': app.project_config.get('xtts_voice_path') or app.global_config.get('xtts_voice_path'),
        'piper_model_path': app.project_config.get('piper_model_path') or app.global_config.get('piper_model_path'),
        'elevenlabs_api_key': app.global_config.get('elevenlabs_api_key'),
        'elevenlabs_voice_id': app.global_config.get('elevenlabs_voice_id'),
        'google_credentials_path': app.global_config.get('google_credentials_path'),
        'google_voice_name': app.global_config.get('google_voice_name'),
    }


def gather_converter_config(app):
    default_workers = max(1, os.cpu_count() // 2 if os.cpu_count() else 4)
    max_workers = int(app.global_config.get('conversion_workers', default_workers))
    return {
        'ffmpeg_filters': app.global_config.get('ffmpeg_filters', {}),
        'conversion_workers': max_workers,
        'audio_output_format': app.global_config.get('audio_output_format', 'ogg')
    }
