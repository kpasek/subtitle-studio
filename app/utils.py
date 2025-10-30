from tkinter import messagebox
from typing import List
import re
import sys
import os
import importlib.util

from app.entity import PatternItem


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


def apply_remove_patterns(lines: List[str], patterns: List[PatternItem]) -> List[str]:
    """
    Applies 'remove' patterns to a list of lines.
    Lines that are empty after substitution are removed.
    Duplicates are also removed.

    Args:
        lines: The list of original subtitle lines.
        patterns: A list of PatternItems to apply.

    Returns:
        A new list of processed, unique, non-empty lines.
    """
    try:
        compiled = [compile_pattern(p) for p in patterns]
    except Exception as e:
        messagebox.showerror("Błąd", f"Nieprawidłowy pattern:\n{e}")
        return []

    out = []
    for line in lines:
        s = line
        for i, pat in enumerate(patterns):
            s = compiled[i].sub(pat.replace, s)
        if s.strip():
            out.append(s)
    seen = set()
    uniq = []
    for l in out:
        if l not in seen:
            uniq.append(l)
            seen.add(l)
    return uniq


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


def apply_replace_patterns(lines: List[str], patterns: List[PatternItem]) -> List[str]:
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
    out = []
    for line in lines:
        s = line
        for i, pat in enumerate(patterns):
            s = compiled[i].sub(pat.replace, s)
        out.append(s)
    return out


def is_installed(package_name: str) -> bool:
    """
    Checks if a Python package is installed without importing it.

    Args:
        package_name: The name of the package (e.g., 'torch').

    Returns:
        True if the package is found, False otherwise.
    """
    return importlib.util.find_spec(package_name) is not None
