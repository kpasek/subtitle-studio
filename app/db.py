import sqlite3
from pathlib import Path
from typing import List
from app.entity import SubtitleLine, PatternItem

class ProjectDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def close(self):
        if self.conn:
            self.conn.close()

    def _create_tables(self):
        cur = self.conn.cursor()
        # Tabela linii dialogowych - dodajemy kolumnę tts_override jeśli nie istnieje
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS lines
                    (
                        uuid
                        TEXT
                        PRIMARY
                        KEY,
                        text
                        TEXT,
                        ord
                        INTEGER,
                        tts_override
                        TEXT
                    )
                    """)

        # Migracja dla starych baz (sprawdzenie czy kolumna istnieje)
        try:
            cur.execute("SELECT tts_override FROM lines LIMIT 1")
        except sqlite3.OperationalError:
            cur.execute("ALTER TABLE lines ADD COLUMN tts_override TEXT")
            self.conn.commit()

        # ... (reszta tabel patterns, settings bez zmian)
        self.conn.commit()

    # --- Operacje na Liniach ---
    def save_lines(self, lines: List[SubtitleLine]):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM lines")
        # Zapisujemy tts_override
        data = [(l.id, l.text, i, l.tts_override) for i, l in enumerate(lines)]
        cur.executemany("INSERT INTO lines (uuid, text, ord, tts_override) VALUES (?, ?, ?, ?)", data)
        self.conn.commit()

    def get_lines(self) -> List[SubtitleLine]:
        cur = self.conn.cursor()
        # Pobieramy tts_override
        cur.execute("SELECT uuid, text, tts_override FROM lines ORDER BY ord")
        return [
            SubtitleLine(
                id=row['uuid'],
                text=row['text'],
                tts_override=row['tts_override']
            ) for row in cur.fetchall()
        ]

    # --- Operacje na Wzorcach ---
    def save_patterns(self, ptype: str, patterns: List[PatternItem]):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM patterns WHERE type = ?", (ptype,))
        data = [(ptype, p.pattern, p.replace, int(p.case_sensitive), int(p.enabled), p.name) for p in patterns]
        cur.executemany("INSERT INTO patterns (type, pattern, replace, case_sensitive, enabled, name) VALUES (?, ?, ?, ?, ?, ?)", data)
        self.conn.commit()

    def get_patterns(self, ptype: str) -> List[PatternItem]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM patterns WHERE type = ?", (ptype,))
        items = []
        for row in cur.fetchall():
            items.append(PatternItem(
                pattern=row['pattern'],
                replace=row['replace'],
                case_sensitive=bool(row['case_sensitive']),
                enabled=bool(row['enabled']),
                name=row['name']
            ))
        return items

    # --- Ustawienia ---
    def set_setting(self, key: str, value: str):
        self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        self.conn.commit()

    def get_setting(self, key: str, default=None):
        cur = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        res = cur.fetchone()
        return res['value'] if res else default