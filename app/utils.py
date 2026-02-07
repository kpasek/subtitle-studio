from tkinter import messagebox
from typing import List
import re
import sys
import os
import importlib.util

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


def apply_remove_patterns(lines: List[Line], patterns: List[PatternItem]) -> List[Line]:
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
        compiled = [compile_pattern(p) for p in patterns]
    except Exception as e:
        messagebox.showerror("Błąd", f"Nieprawidłowy pattern:\n{e}")
        return []

    for line in lines:
        s = line.text
        for i, pat in enumerate(patterns):
            s = compiled[i].sub(pat.replace, s)
        line.text = s

    return lines


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
    compiled = [compile_pattern(p) for p in patterns]

    for line in lines:
        s = line.tts_text
        for i, pat in enumerate(patterns):
            s = compiled[i].sub(pat.replace, s)
        line.tts_text = s
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
