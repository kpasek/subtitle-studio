from tkinter import messagebox
from typing import List
import re
import sys
import os
import importlib.util
from pathlib import Path

from app.entity import Line, PatternItem


def compile_pattern(pat: PatternItem) -> re.Pattern:
    """
    Compiles a regex pattern from a PatternItem object.

    Args:
        pat: The PatternItem containing the regex string and flags.

    Returns:
        A compiled regex pattern.
    """
    flags = re.IGNORECASE if not pat.case_sensitive else 0
    return re.compile(pat.pattern, flags)


def apply_remove_patterns(lines: List[Line], patterns: List[PatternItem], remove_empty: bool = True) -> List[Line]:
    """
    Applies 'remove' patterns to a list of lines.
    Does NOT automatically remove empty lines or duplicates anymore.

    Args:
        lines: The list of original subtitle lines.
        patterns: A list of PatternItems to apply.

    Returns:
        A new list of processed lines (regex applied only).
    """
    try:
        all_enabled = [p for p in patterns if p.enabled]
        compiled = [compile_pattern(p) for p in all_enabled]
    except Exception as e:
        messagebox.showerror("Błąd", f"Nieprawidłowy pattern:\n{e}")
        return []

    if not compiled:
        return lines
    
    filtered_lines = []
    for i, line in enumerate(lines):
        # Skip DONE lines (do not modify, preserve in list)
        if getattr(line, 'status_flag', None) == "DONE":
            filtered_lines.append(line)
            continue
            
        s = line.get_text()
        for i, pat in enumerate(all_enabled):
            s = compiled[i].sub(pat.replace, s)
        if remove_empty and not s.strip():
            continue
        line.set_text(s)
        filtered_lines.append(line)

    return filtered_lines


def resource_path(relative_path: str) -> str:
    """
    Get the absolute path to a resource, works for dev and for PyInstaller.

    Args:
        relative_path: The path relative to the application's root.

    Returns:
        The absolute path to the resource.
    """
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def apply_replace_patterns(lines: List[Line], patterns: List[PatternItem]) -> List[Line]:
    """
    Applies 'replace' patterns to a list of lines.
    Empty lines are preserved.

    Args:
        lines: The list of 'cleaned' subtitle lines.
        patterns: A list of PatternItems to apply.

    Returns:
        A new list of processed lines.
    """
    all_enabled = [p for p in patterns if p.enabled]
    compiled = [compile_pattern(p) for p in all_enabled]

    for line in lines:
        # Skip DONE lines
        if getattr(line, 'status_flag', None) == "DONE":
            continue

        # 1. Apply to visual text
        s = line.get_text()
        for i, pat in enumerate(all_enabled):
            s = compiled[i].sub(pat.replace, s)
        line.set_text(s)
        
        # 2. Apply to TTS text override if present
        if line.tts_text is not None:
            s_tts = line.get_tts_text()
            for i, pat in enumerate(all_enabled):
                s_tts = compiled[i].sub(pat.replace, s_tts)
            line.set_tts_text(s_tts)
            
    return lines


def is_installed(package_name: str) -> bool:
    """
    Checks if a Python package is installed without importing it.

    Args:
        package_name: The name of the package (e.g., 'torch').

    Returns:
        True if the package is found, False otherwise.
    """
    return importlib.util.find_spec(package_name) is not None


def project_generated_dir(project_path: Path) -> Path:
    """Zwraca katalog generated powiązany z plikiem projektu."""
    return project_path.parent / "generated"


def project_subtitles_dir(project_path: Path) -> Path:
    """Zwraca katalog subtitles powiązany z plikiem projektu."""
    return project_path.parent / "subtitles"


def project_ready_dir(project_path: Path) -> Path:
    """Zwraca katalog ready powiązany z plikiem projektu."""
    return project_path.parent / "ready"


def ready_dir_from_audio_dir(audio_dir: Path) -> Path:
    """Zwraca katalog ready na podstawie katalogu audio (zakłada, że ready jest obok)."""
    return audio_dir.parent / "ready"


def ensure_project_dirs(project_path: Path) -> None:
    """Tworzy katalogi generated/subtitles/ready w projekcie, jeśli nie istnieją."""
    for directory in (project_generated_dir(project_path),
                      project_subtitles_dir(project_path),
                      project_ready_dir(project_path)):
        directory.mkdir(parents=True, exist_ok=True)

