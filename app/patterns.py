from typing import List, Optional, Tuple
from app.entity import PatternItem, Line
from app.utils import apply_remove_patterns, apply_replace_patterns
from ui.processing_summary import ProcessingSummaryWindow
from tkinter import messagebox
import datetime
import re


BUILTIN_REMOVE = [
    (PatternItem(r"^\[[^\]]*\]+$", "", False), "Usuń całe linie [.*]"),
    (PatternItem(r"^\<[^>]*>+$", "", False), "Usuń całe linie <.*>"),
    (PatternItem(r"^\{[^\}]*\}+$", "", False), "Usuń całe linie {.*}"),
    (PatternItem(r"^\([^\)]*\)+$", "", False), "Usuń całe linie (.*)"),
    (PatternItem(r"^[A-Z\?\!\.]{,4}$", "", True), None),
    (PatternItem(r" ", "", False), "Usuń niektóre niewidoczne znaki"),
]
BUILTIN_REPLACE = [
    (PatternItem(r"\[[^\]]*\]+", " ", False), "Usuń treść [.*]"),
    (PatternItem(r"\<[^>]*>+", " ", False), "Usuń treść <.*>"),
    (PatternItem(r"\{[^\}]*\}+", " ", False), "Usuń treść {.*}"),
    (PatternItem(r"\([^\)]*\)+", " ", False), "Usuń treść (.*)"),
    (PatternItem(r"…", "...", False), "Popraw trójkropek"),
    (PatternItem(r"\.{2,}", ".", False), "Trójkropek > kropka"),
    (PatternItem(r"\?!", "?", False), "?! -> ?"),
    (PatternItem(r"\?{2,}", "?", False), "?(?)+ -> ?"),
    (PatternItem(r"[@#$^&*\(\)\{\}]+", " ", False), "Usuń znaki specjalne jak @#$"),
    (PatternItem(r"\s{2,}", " ", False), "Zamień białe znaki na spacje"),
    (PatternItem(r"^[-.\"\']", "", False), "Usuń wiodące znaki specjalne (-.\"')"),
    (PatternItem(r"[-\"\']$", "", False), "Usuń kończące znaki specjalne (-\"')"),
]


LineList = List[Line]


def gather_active_patterns(custom_remove: List[PatternItem], custom_replace: List[PatternItem]):
    """Zbiera wszystkie aktywne wzorce (tylko custom, builtin są już przekazane przez caller)."""
    remove_patterns = [p for p in custom_remove if p.enabled]
    replace_patterns = [p for p in custom_replace if p.enabled]
    return remove_patterns, replace_patterns


def get_patterns_signature(patterns: List[PatternItem]):
    """Tworzy sygnaturę (hashowalną krotkę) dla listy wzorców."""
    return tuple((p.pattern, p.replace, p.case_sensitive, p.enabled) for p in patterns)


def apply_patterns(app, force_refresh=False):
    """Aplikuje wzorce usuwania i zamiany na liniach aplikacji."""
    lines: LineList = app.lines
    if not lines:
        return

    lines = apply_remove_patterns(lines, app.custom_remove)
    apply_replace_patterns(lines, app.custom_replace)

    # Aktualizacja widoku
    app._update_subtitle_panel_content()
    app.set_status("Zaktualizowano podgląd.")


def open_pattern_manager(app):
    from app.pattern_manager import PatternManagerWindow
    if app.pattern_manager_window is None or not app.pattern_manager_window.winfo_exists():
        app.pattern_manager_window = PatternManagerWindow(app)
        # Podpinamy się pod zdarzenie zamknięcia okna "krzyżykiem"
        app.pattern_manager_window.protocol("WM_DELETE_WINDOW", lambda: _on_pattern_manager_close(app))
    else:
        app.pattern_manager_window.lift()


def _on_pattern_manager_close(app):
    """Obsługa zamknięcia menedżera wzorców - odświeżenie widoku."""
    if app.pattern_manager_window:
        app.pattern_manager_window.destroy()
        app.pattern_manager_window = None
    # Odśwież widok (przelicz ponownie wzorce i zaktualizuj listę)
    apply_patterns(app)


def _refresh_custom_lists(app):
    if app.pattern_manager_window and app.pattern_manager_window.winfo_exists():
        app.pattern_manager_window.refresh_ui()


def open_add_remove_pattern(app):
    from audio.pattern_editor import PatternEditorWindow
    PatternEditorWindow(app, pattern_type='remove', callback=lambda n, o, t: handle_pattern_update(app, n, o, t),
                        existing_pattern=None)


def open_add_replace_pattern(app):
    from audio.pattern_editor import PatternEditorWindow
    PatternEditorWindow(app, pattern_type='replace', callback=lambda n, o, t: handle_pattern_update(app, n, o, t),
                        existing_pattern=None)


def open_edit_pattern(app, pattern: PatternItem, target_list: List[PatternItem]):
    from audio.pattern_editor import PatternEditorWindow
    pattern_type = 'remove' if target_list is app.custom_remove else 'replace'
    PatternEditorWindow(app, pattern_type=pattern_type, callback=lambda n, o, t: handle_pattern_update(app, n, o, t),
                        existing_pattern=pattern)


def handle_pattern_update(app, new_pattern: PatternItem, old_pattern: Optional[PatternItem], pattern_type: str):
    target_list = app.custom_remove if pattern_type == 'remove' else app.custom_replace
    if old_pattern:
        try:
            index = target_list.index(old_pattern)
            target_list[index] = new_pattern
        except ValueError:
            target_list.append(new_pattern)
    else:
        target_list.append(new_pattern)
    app.mark_as_unsaved()
    app.set_status("Zaktualizowano wzorce.")
    _refresh_custom_lists(app)
    apply_patterns(app)


def _clear_custom_list(app, clear_type: str):
    """Czyści listę wzorców własnych."""
    if clear_type == 'remove':
        app.custom_remove.clear()
    else:
        app.custom_replace.clear()
    app.mark_as_unsaved()
    app.set_status(f"Wyczyszczono listę {clear_type}.")
    _refresh_custom_lists(app)
    apply_patterns(app)


def add_remove_pattern_from_selection(app, event=None):
    """Dodaje wzorzec wycinający (wywołane z panelu)."""
    if app.selected_line_index is None:
        return
    lines: LineList = app.lines
    try:
        line: Line = lines[app.selected_line_index]
        text = line.tts_text
        escaped = re.escape(text)
        if any(p.pattern == escaped for p in app.custom_remove): return
        app.custom_remove.append(PatternItem(escaped, "", True))
        app.mark_as_unsaved()
        _refresh_custom_lists(app)
        app.set_status("Dodano wzorzec wycinający.")
        apply_patterns(app)
    except IndexError:
        pass


def add_replace_pattern_from_selection(app, event=None, from_menu=False):
    from audio.pattern_editor import PatternEditorWindow
    if app.selected_line_index is None:
        return
    lines: LineList = app.lines
    try:
        line: Line = lines[app.selected_line_index]
        text = line.tts_text.strip()
        if not text: return
        win = PatternEditorWindow(app, 'replace', lambda n, o, t: handle_pattern_update(app, n, o, t), None)
        win.ent_pattern.insert(0, text)
        win.ent_replace.insert(0, text)
        win.var_case_sensitive.set(True)
        if from_menu: win.lift()
    except IndexError:
        pass


# --- PROCES PRZETWARZANIA ---

def apply_processing(app):
    """Zatwierdzenie zmian (okno podsumowania)."""
    lines: LineList = app.lines
    if not lines:
        messagebox.showwarning('Brak pliku', 'Najpierw wczytaj plik z napisami.')
        return

    rem_patterns, _ = gather_active_patterns(app.custom_remove, app.custom_replace)

    lines = apply_remove_patterns(lines, rem_patterns)

    changes_count = 0
    for i, line in enumerate(lines):
        if line.original_text != line.text:
            changes_count += 1

    ProcessingSummaryWindow(
        app, len(lines), changes_count,
        manual_edits_count=changes_count,
        callback=lambda remove_empty, remove_duplicates: _finalize_processing(app, remove_empty, remove_duplicates)
    )


def _finalize_processing(app, remove_empty: bool, remove_duplicates: bool):
    """
    Zatwierdza zmiany zgodnie z nową logiką (przeniesiona z `studio`):
    1. Aplikuje wzorce (remove + replace).
    2. Aplikuje edycje ręczne.
    3. Filtruje (puste/duplikaty).
    4. Zachowuje dane weryfikacji dla niezmienionego tekstu TTS.
    5. Zapisuje wynik do nowego pliku z timestampem.
    6. Ustawia nowy plik jako aktualny w projekcie.
    """
    # 1. Pobierz aktywne wzorce
    rem_patterns, repl_patterns = gather_active_patterns(app.custom_remove, app.custom_replace)

    # Zapamiętaj starą listę linii dla celów mapowania metadanych
    old_lines: LineList = list(app.lines)
    
    # Aplikujemy wzorce usuwające (kończące proces oczyszczania "clean")
    clone_lines = apply_remove_patterns(old_lines, rem_patterns)

    # 3. Filtrowanie (Puste linie i Duplikaty)
    final_objs = []
    seen_texts = set()

    for obj in clone_lines:
        txt = obj.text
        if remove_empty and not txt.strip():
            continue
        if remove_duplicates:
            norm = txt.strip()
            if norm in seen_texts:
                continue
            seen_texts.add(norm)
            
        final_objs.append(obj)

    if not app.current_project_path:
        messagebox.showerror("Błąd", "Brak otwartego pliku projektu.")
        return

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    original_stem = app.current_project_path.stem
    new_filename = f"{timestamp}_{original_stem}.csv"
    new_path = app.current_project_path.parent / 'subtitles' / new_filename

    try:
        from app.io import save_lines_to_file
        save_lines_to_file(str(new_path), final_objs)
    except Exception as e:
        messagebox.showerror("Błąd zapisu", f"Nie udało się zapisać nowego pliku:\n{e}")
        return

    app.loaded_path = new_path
    app.lines = final_objs

    # Wyłączamy wzorce usuwające (zostały "wypalone" w tekst)
    for p in app.custom_remove:
        p.enabled = False

    app._cache_replace_result = None
    app._last_replace_signature = None

    app._refresh_custom_lists()
    from app.project import save_project
    save_project(app)
    apply_patterns(app)

    app.set_status(f"Zatwierdzono. Utworzono nową wersję: {new_filename}")
