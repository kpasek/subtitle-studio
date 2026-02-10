
def format_percent(value: float | None) -> str | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    numeric = max(0.0, min(numeric, 1.0))
    return f"{numeric * 100:.0f}%"


def normalize_to_percent(value: float | str | None) -> float | None:
    if value is None or value == '':
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 1:
        numeric = numeric / 100.0
    numeric = max(0.0, min(numeric, 1.0))
    return numeric