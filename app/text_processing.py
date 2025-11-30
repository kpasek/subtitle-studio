import re
import difflib
from typing import List, Tuple
from app.entity import PatternItem, SubtitleLine


def compile_pattern(pat: PatternItem) -> re.Pattern:
    """Kompiluje obiekt PatternItem do obiektu re.Pattern."""
    flags = re.IGNORECASE if not pat.case_sensitive else 0
    return re.compile(pat.pattern, flags)


def apply_remove_patterns(lines: List[str], patterns: List[PatternItem]) -> List[str]:
    """
    Stosuje listę wzorców wycinających do listy tekstów.
    Usuwa puste linie powstałe w wyniku wycięcia.
    """
    if not patterns:
        return [l for l in lines if l.strip()]

    compiled = [compile_pattern(p) for p in patterns]
    out = []

    for line in lines:
        s = line
        for i, pat in enumerate(patterns):
            # Używamy skompilowanego wzorca
            s = compiled[i].sub(pat.replace, s)

        # Dodajemy tylko jeśli po czyszczeniu coś zostało
        if s.strip():
            out.append(s.strip())

    return out


def apply_replace_patterns(lines: List[str], patterns: List[PatternItem]) -> List[str]:
    """
    Stosuje listę wzorców podmieniających. Nie usuwa linii.
    """
    if not patterns:
        return lines

    compiled = [compile_pattern(p) for p in patterns]
    out = []
    for line in lines:
        s = line
        for i, pat in enumerate(patterns):
            s = compiled[i].sub(pat.replace, s)
        out.append(s)
    return out


def reconcile_lines(old_lines: List[SubtitleLine], new_text_lines: List[str]) -> List[SubtitleLine]:
    """
    Inteligentnie łączy starą listę obiektów (z ID) z nową listą tekstów (z edytora).
    Używa difflib, aby zachować ID dla linii, które nie zostały usunięte.

    Args:
        old_lines: Lista obiektów SubtitleLine (stan przed edycją).
        new_text_lines: Lista stringów (stan po edycji w polu tekstowym).

    Returns:
        Nowa lista SubtitleLine, gdzie możliwe zachowano ID.
    """
    old_texts = [line.text for line in old_lines]
    # Używamy SequenceMatcher do znalezienia najdłuższego wspólnego podciągu / różnic
    matcher = difflib.SequenceMatcher(None, old_texts, new_text_lines)

    result_lines = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Linie bez zmian - kopiujemy obiekty (zachowujemy ID i audio)
            result_lines.extend(old_lines[i1:i2])

        elif tag == 'replace':
            # Zamiana bloku linii. Próbujemy zachować ID dla odpowiadających indeksów.
            # To strategia heurystyczna: jeśli zmieniono literówkę, ID zostanie.
            # Jeśli zmieniono całe zdanie, ID też zostanie (audio do przenerowania).
            len_old = i2 - i1
            len_new = j2 - j1

            for k in range(len_new):
                if k < len_old:
                    # Aktualizacja tekstu w istniejącym slocie
                    existing = old_lines[i1 + k]
                    result_lines.append(SubtitleLine(id=existing.id, text=new_text_lines[j1 + k]))
                else:
                    # Nowa linia (nadmiarowa w stosunku do starego bloku)
                    result_lines.append(SubtitleLine.new(new_text_lines[j1 + k]))

        elif tag == 'delete':
            # Linie usunięte - pomijamy
            pass

        elif tag == 'insert':
            # Całkiem nowe linie wstawione - generujemy nowe ID
            for k in range(j1, j2):
                result_lines.append(SubtitleLine.new(new_text_lines[k]))

    return result_lines


def filter_indices_by_query(lines: List[SubtitleLine], query: str,
                            remove_patterns: List[PatternItem],
                            replace_patterns: List[PatternItem],
                            apply_replace: bool = True) -> List[int]:
    """
    Zwraca indeksy linii pasujących do zapytania.
    Sprawdza zarówno tekst surowy, jak i przetworzony.
    """
    if not query:
        return list(range(len(lines)))

    q = query.lower()
    indices = []

    # Prekompilacja dla wydajności pętli
    comp_rem = [compile_pattern(p) for p in remove_patterns if p.enabled]
    comp_rep = [compile_pattern(p) for p in replace_patterns if p.enabled] if apply_replace else []

    for i, line in enumerate(lines):
        raw_text = line.text

        # Symulacja widoku przetworzonego
        processed = raw_text
        for c in comp_rem:
            processed = c.sub(c.pattern, processed)  # Tu uproszczenie, remove patterns mają replace=""

        for c in comp_rep:
            processed = c.sub(c.pattern, processed)  # Tu replace="coś"

        if q in raw_text.lower() or q in processed.lower():
            indices.append(i)

    return indices