from typing import List, Tuple
from app.entity import PatternItem, Line
from app.utils import apply_remove_patterns, apply_replace_patterns
from ui.processing_summary import ProcessingSummaryWindow
from tkinter import messagebox
import datetime
import re


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
    if not app.lines:
        return

    apply_remove_patterns(app.lines, app.builtin_remove + app.custom_remove)
    apply_replace_patterns(app.lines, app.builtin_replace + app.custom_replace)

    # Aktualizacja widoku
    app._update_subtitle_panel_content()
    app.set_status("Zaktualizowano podgląd.")


# --- PROCES PRZETWARZANIA ---

def apply_processing(app):
    """Zatwierdzenie zmian (okno podsumowania)."""
    if not app.lines:
        messagebox.showwarning('Brak pliku', 'Najpierw wczytaj plik z napisami.')
        return

    rem_patterns, _ = gather_active_patterns(app.custom_remove, app.custom_replace)

    apply_remove_patterns(app.lines, rem_patterns)

    changes_count = 0
    for i, line in enumerate(app.lines):
        if line.original_text != line.text:
            changes_count += 1

    ProcessingSummaryWindow(
        app, len(app.lines), changes_count,
        manual_edits_count=changes_count,
        callback=lambda remove_empty, remove_duplicates: _finalize_processing(app, remove_empty, remove_duplicates)
    )


def _finalize_processing(app, remove_empty: bool, remove_duplicates: bool):
    """
    Zatwierdza zmiany zgodnie z nową logiką (przeniesiona z `studio`):
    1. Aplikuje wzorce (remove + replace).
    2. Aplikuje edycje ręczne.
    3. Filtruje (puste/duplikaty).
    4. Zapisuje wynik do nowego pliku z timestampem.
    5. Ustawia nowy plik jako aktualny w projekcie.
    """
    # 1. Pobierz aktywne wzorce
    rem_patterns, _ = gather_active_patterns(app.custom_remove, app.custom_replace)

    # 2. Aplikuj wzorce usuwające na ORYGINALNYCH liniach
    working_lines = list(app.original_lines) if hasattr(app, 'original_lines') else [l.original_text for l in app.lines]

    # wrapped apply_remove_patterns for strings: create temporary Line objects
    temp_lines = [Line(original_text=s, text=s, tts_text=s) for s in working_lines]
    processed = apply_remove_patterns(temp_lines, rem_patterns)
    processed_lines = [l.text for l in processed]

    for idx, text in app.manual_edits.items():
        if 0 <= idx < len(processed_lines):
            processed_lines[idx] = text

    # 5. Filtrowanie (Puste linie i Duplikaty)
    final_lines = []
    seen = set()

    for line in processed_lines:
        if remove_empty and not line.strip():
            continue
        if remove_duplicates:
            normalized = line.strip()
            if normalized in seen:
                continue
            seen.add(normalized)
        final_lines.append(line)

    if not app.current_project_path:
        messagebox.showerror("Błąd", "Brak otwartego pliku projektu.")
        return

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    original_stem = app.current_project_path.stem
    new_filename = f"{timestamp}_{original_stem}.csv"
    new_path = app.current_project_path.parent / 'subtitles' / new_filename

    # Prepare Line objects
    new_lines = [Line(original_text=s, text=s, tts_text=s) for s in final_lines]

    try:
        from app.io import save_lines_to_file
        save_lines_to_file(str(new_path), new_lines)
    except Exception as e:
        messagebox.showerror("Błąd zapisu", f"Nie udało się zapisać nowego pliku:\n{e}")
        return

    app.loaded_path = new_path
    app.original_lines = final_lines
    app.processed_clean = list(final_lines)

    for p in app.custom_remove:
        p.enabled = False

    app._cache_replace_result = None
    app._last_replace_signature = None

    app._refresh_custom_lists()
    app.save_project()
    app.apply_patterns()

    app.set_status(f"Zatwierdzono. Utworzono nową wersję: {new_filename}")
