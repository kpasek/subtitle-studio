from tkinter import messagebox
from typing import List
import re
import sys
import os
import importlib.util
import difflib

from app.entity import PatternItem, SubtitleLine


def compile_pattern(pat: PatternItem) -> re.Pattern:
    flags = re.IGNORECASE if not pat.case_sensitive else 0
    return re.compile(pat.pattern, flags)


def apply_remove_patterns(lines: List[str], patterns: List[PatternItem]) -> List[str]:
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
        # UWAGA: W nowym podejściu edytora "z palca" automatyczne usuwanie pustych linii
        # może być mylące, ale zachowujemy logikę dla kompatybilności z funkcjami czyszczącymi.
        if s.strip():
            out.append(s)

    # Usuwanie duplikatów (w logice edytora może być niepożądane, ale w patternach tak)
    seen = set()
    uniq = []
    for l in out:
        if l not in seen:
            uniq.append(l)
            seen.add(l)
    return uniq


def resource_path(relative_path: str) -> str:
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def apply_replace_patterns(lines: List[str], patterns: List[PatternItem]) -> List[str]:
    compiled = [compile_pattern(p) for p in patterns]
    out = []
    for line in lines:
        s = line
        for i, pat in enumerate(patterns):
            s = compiled[i].sub(pat.replace, s)
        out.append(s)
    return out


def is_installed(package_name: str) -> bool:
    return importlib.util.find_spec(package_name) is not None


def reconcile_lines(old_lines: List[SubtitleLine], new_text_lines: List[str]) -> List[SubtitleLine]:
    """
    Porównuje starą listę obiektów SubtitleLine z nową listą stringów (z edytora).
    Próbuje zachować ID (a więc i audio) dla linii, które są podobne lub identyczne.
    """
    old_texts = [line.text for line in old_lines]
    matcher = difflib.SequenceMatcher(None, old_texts, new_text_lines)

    result_lines = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Linie identyczne - przepisz obiekty z zachowaniem ID
            result_lines.extend(old_lines[i1:i2])
        elif tag == 'replace':
            # Linie zmienione - to zależy od strategii.
            # Jeśli tekst się zmienił, zazwyczaj chcemy nowe audio, ale zachowanie ID
            # pozwala systemowi wiedzieć, że to "ta sama linia, ale inna wersja".
            # Dla bezpieczeństwa audio: Jeśli tekst się zmienił drastycznie, audio i tak będzie do bani.
            # Przyjmijmy strategię: Zachowaj ID, ale oznacz jako "zmienione" (to obsłuży GUI).
            for k in range(j2 - j1):
                # Spróbuj dopasować 1:1, reszta jako nowe
                if k < (i2 - i1):
                    # Aktualizacja tekstu w istniejącej linii
                    existing_line = old_lines[i1 + k]
                    result_lines.append(SubtitleLine(id=existing_line.id, text=new_text_lines[j1 + k]))
                else:
                    # Nadmiarowe nowe linie w bloku replace
                    result_lines.append(SubtitleLine.new(new_text_lines[j1 + k]))
        elif tag == 'delete':
            # Linie usunięte - po prostu ich nie dodajemy do wyniku
            pass
        elif tag == 'insert':
            # Nowe linie - utwórz nowe obiekty z nowym ID
            for k in range(j1, j2):
                result_lines.append(SubtitleLine.new(new_text_lines[k]))

    return result_lines