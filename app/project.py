import json
import os
from pathlib import Path
from typing import Optional
from tkinter import filedialog, messagebox


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
        app.project_config = cfg

        _update_recent_projects(app, str(app.current_project_path))

        app.names_list = cfg.get("names_list", [])

        all_vars = app.builtin_remove_state + app.builtin_replace_state
        traces = {}
        for var in all_vars:
            if var.trace_info():
                trace_id = var.trace_info()[0][1]
                traces[var._name] = (var, trace_id)
                var.trace_remove("write", trace_id)

        for i, val in enumerate(cfg.get("builtin_remove_state", [])):
            if i < len(app.builtin_remove_state):
                app.builtin_remove_state[i].set(bool(val))
        for i, val in enumerate(cfg.get("builtin_replace_state", [])):
            if i < len(app.builtin_replace_state):
                app.builtin_replace_state[i].set(bool(val))

        for name, (var, trace_id) in traces.items():
            var.trace_add("write", app.mark_as_unsaved)

        app.custom_remove = [type(app.custom_remove[0]).from_json(x) if app.custom_remove else __import__('app').entity.PatternItem.from_json(x) for x in cfg.get("custom_remove", [])]
        app.custom_replace = [type(app.custom_replace[0]).from_json(x) if app.custom_replace else __import__('app').entity.PatternItem.from_json(x) for x in cfg.get("custom_replace", [])]
        app._refresh_custom_lists()

        subtitle_path = cfg.get("subtitle_path")
        if subtitle_path and Path(subtitle_path).exists():
            app.load_file(subtitle_path, bypass_save_check=True)
        else:
            app.lines = []
            app.apply_patterns()
            if app.lbl_filename:
                app.lbl_filename.configure(text="Brak wczytanego pliku")

        audio_path_str = cfg.get("audio_path")
        app.audio_dir = Path(audio_path_str) if audio_path_str else None

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
        "audio_path": str(app.audio_dir.absolute()) if app.audio_dir else None,
        "names_list": app.names_list,
        "active_tts_model": app.project_config.get('active_tts_model', 'XTTS'),
        "base_audio_speed": app.project_config.get('base_audio_speed', 1.1)
    })
    return current_cfg


def _load_app_config(app, only_config=False):
    if os.path.exists(__import__('app').io.APP_CONFIG):
        try:
            with open(__import__('app').io.APP_CONFIG, "r", encoding="utf-8") as f:
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
        with open(__import__('app').io.APP_CONFIG, "w", encoding="utf-8") as f:
            json.dump(app.global_config, f, indent=2)
    except Exception:
        pass


def save_global_config(app, data: dict):
    for key, value in data.items():
        app.global_config[key] = value

    try:
        with open(__import__('app').io.APP_CONFIG, "w", encoding="utf-8") as f:
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
