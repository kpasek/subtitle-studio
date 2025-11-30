from app.entity import PatternItem

BUILTIN_PATTERNS = {
    "subtitle": [ # Dawne "Usuwanie"
        PatternItem(pattern=r"\{.*?\}", name="Nawiasy klamrowe {Didaskalia}"),
        PatternItem(pattern=r"\[.*?\]", name="Nawiasy kwadratowe [Opis]"),
        PatternItem(pattern=r"\(.*?\)", name="Nawiasy okrągłe (Inne)"),
        PatternItem(pattern=r"<.*?>", name="Tagi HTML <>"),
        PatternItem(pattern=r"\s{2,}", replace=" ", name="Podwójne spacje"),
    ],
    "tts": [ # Dawne "Podmiana"
        PatternItem(pattern=r"NPC:", replace="", name="Prefix NPC:"),
        PatternItem(pattern=r"Player:", replace="", name="Prefix Player:"),
        PatternItem(pattern=r"\.\.\.", replace=".", name="Wielokropek na kropkę"),
    ]
}