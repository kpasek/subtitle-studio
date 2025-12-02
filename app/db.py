import sqlite3
import json
from pathlib import Path
from typing import List, Any, Optional
from app.entity import SubtitleLine, PatternItem

# --- DEFINICJE MIGRACJI ---
# Lista słowników definiująca kolejne zmiany w bazie.
# Skrypty będą uruchamiane w kolejności indeksów listy.

MIGRATIONS = [
    {
        "version": 1,
        "name": "initial_structure_v2",
        "script": """
                  -- 1. Tabela migracji do śledzenia historii zmian
                  CREATE TABLE IF NOT EXISTS _migrations
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      version
                      INTEGER
                      NOT
                      NULL
                      UNIQUE,
                      name
                      TEXT
                      NOT
                      NULL,
                      executed_at
                      TIMESTAMP
                      DEFAULT
                      CURRENT_TIMESTAMP
                  );

                  -- 2. Tabela z oryginalnymi liniami (ID jako INT)
                  CREATE TABLE IF NOT EXISTS original_lines
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      text
                      TEXT
                      NOT
                      NULL,
                      ord
                      INTEGER
                      NOT
                      NULL
                  );

                  -- 3. Tabela zmian dla napisów (wyświetlanie)
                  CREATE TABLE IF NOT EXISTS modified_subtitle_lines
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      original_line_id
                      INTEGER
                      NOT
                      NULL,
                      text
                      TEXT,
                      change_source
                      TEXT
                      DEFAULT
                      'NONE', -- 'MANUAL', 'PATTERN', 'DUPLICATE'
                      FOREIGN
                      KEY
                  (
                      original_line_id
                  ) REFERENCES original_lines
                  (
                      id
                  ) ON DELETE CASCADE
                      );

                  -- 4. Tabela zmian dla TTS (audio)
                  CREATE TABLE IF NOT EXISTS modified_tts_lines
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      original_line_id
                      INTEGER
                      NOT
                      NULL,
                      text
                      TEXT,
                      change_source
                      TEXT
                      DEFAULT
                      'NONE',
                      FOREIGN
                      KEY
                  (
                      original_line_id
                  ) REFERENCES original_lines
                  (
                      id
                  ) ON DELETE CASCADE
                      );

                  -- 5. Tabela wzorców (wspólna dla tts i subtitle, rozróżniana polem 'type')
                  CREATE TABLE IF NOT EXISTS patterns
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      type
                      TEXT
                      NOT
                      NULL, -- 'subtitle' lub 'tts'
                      pattern
                      TEXT
                      NOT
                      NULL,
                      replacement
                      TEXT,
                      case_sensitive
                      INTEGER
                      DEFAULT
                      1,
                      enabled
                      INTEGER
                      DEFAULT
                      1,
                      applied
                      INTEGER
                      DEFAULT
                      0,    -- informacja czy został zastosowany
                      name
                      TEXT
                  );

                  -- 6. Tabela ustawień z typowaniem
                  CREATE TABLE IF NOT EXISTS settings
                  (
                      key
                      TEXT
                      PRIMARY
                      KEY,
                      value
                      TEXT,
                      value_type
                      TEXT -- 'str', 'int', 'float', 'bool', 'json'
                  );
                  """
    }
    # Tutaj w przyszłości można dodać kolejne migracje, np.:
    # { "version": 2, "name": "add_column_x", "script": "ALTER TABLE ..." }
]


class ProjectDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self):
        """Otwiera połączenie i automatycznie uruchamia brakujące migracje."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")  # Ważne dla SQLite
        self.conn.row_factory = sqlite3.Row

        # Inicjalizacja systemu migracji
        self._init_migration_table()
        self._run_migrations()

    def close(self):
        if self.conn:
            self.conn.close()

    # --- SYSTEM MIGRACJI ---

    def _init_migration_table(self):
        """Upewnia się, że tabela migracji istnieje przed sprawdzeniem wersji."""
        self.conn.execute("""
                          CREATE TABLE IF NOT EXISTS _migrations
                          (
                              id
                              INTEGER
                              PRIMARY
                              KEY
                              AUTOINCREMENT,
                              version
                              INTEGER
                              NOT
                              NULL
                              UNIQUE,
                              name
                              TEXT
                              NOT
                              NULL,
                              executed_at
                              TIMESTAMP
                              DEFAULT
                              CURRENT_TIMESTAMP
                          )
                          """)
        self.conn.commit()

    def _run_migrations(self):
        """Sprawdza, które migracje zostały wykonane i uruchamia brakujące."""
        cur = self.conn.cursor()

        # Pobierz wykonane wersje
        cur.execute("SELECT version FROM _migrations ORDER BY version ASC")
        executed_versions = {row['version'] for row in cur.fetchall()}

        for migration in MIGRATIONS:
            ver = migration['version']
            if ver not in executed_versions:
                print(f"[DB] Uruchamianie migracji v{ver}: {migration['name']}...")
                try:
                    cur.executescript(migration['script'])
                    cur.execute("INSERT INTO _migrations (version, name) VALUES (?, ?)", (ver, migration['name']))
                    self.conn.commit()
                except Exception as e:
                    self.conn.rollback()
                    raise RuntimeError(f"Błąd migracji v{ver}: {e}")

    # --- LOGIKA BIZNESOWA (CRUD) ---

    def save_lines(self, lines: List[SubtitleLine]):
        """
        Zapisuje stan linii.
        UWAGA: W tej prostej implementacji czyścimy tabele i wstawiamy na nowo,
        aby zachować spójność ID i kolejność (chyba że zależy nam na trwałości ID między sesjami,
        wtedy należałoby robić UPSERT).
        Dla uproszczenia przy 'drastycznych zmianach' - wipe & insert.
        """
        cur = self.conn.cursor()

        # Czyścimy tabele linii (kolejność usuwania ważna ze względu na FK)
        cur.execute("DELETE FROM modified_tts_lines")
        cur.execute("DELETE FROM modified_subtitle_lines")
        cur.execute("DELETE FROM original_lines")

        for idx, line in enumerate(lines):
            # 1. Oryginał
            cur.execute("INSERT INTO original_lines (text, ord) VALUES (?, ?)", (line.original_text, idx))
            new_id = cur.lastrowid
            line.id = new_id  # Aktualizujemy ID w obiekcie w pamięci

            # 2. Modified Subtitle
            cur.execute("""
                        INSERT INTO modified_subtitle_lines (original_line_id, text, change_source)
                        VALUES (?, ?, ?)
                        """, (new_id, line.subtitle_text, line.subtitle_change_source))

            # 3. Modified TTS
            cur.execute("""
                        INSERT INTO modified_tts_lines (original_line_id, text, change_source)
                        VALUES (?, ?, ?)
                        """, (new_id, line.tts_text, line.tts_change_source))

        self.conn.commit()

    def get_lines(self) -> List[SubtitleLine]:
        """Pobiera kompletny widok linii (JOIN trzech tabel)."""
        query = """
                SELECT o.id, \
                       o.text          as orig_text, \
                       o.ord, \
                       s.text          as sub_text, \
                       s.change_source as sub_src, \
                       t.text          as tts_text, \
                       t.change_source as tts_src
                FROM original_lines o
                         LEFT JOIN modified_subtitle_lines s ON o.id = s.original_line_id
                         LEFT JOIN modified_tts_lines t ON o.id = t.original_line_id
                ORDER BY o.ord ASC \
                """
        cur = self.conn.cursor()
        cur.execute(query)

        results = []
        for row in cur.fetchall():
            line = SubtitleLine(
                id=row['id'],
                original_text=row['orig_text'],
                subtitle_text=row['sub_text'] if row['sub_text'] is not None else row['orig_text'],
                subtitle_change_source=row['sub_src'] if row['sub_src'] else "NONE",
                tts_text=row['tts_text'] if row['tts_text'] is not None else row['orig_text'],
                tts_change_source=row['tts_src'] if row['tts_src'] else "NONE",
                ord=row['ord']
            )
            results.append(line)
        return results

    def save_patterns(self, patterns: List[PatternItem]):
        """Zapisuje wzorce (nadpisuje wszystko dla danego typu lub globalnie)."""
        if not patterns: return

        cur = self.conn.cursor()
        cur.execute("DELETE FROM patterns")  # Prosty reset tabeli

        data = []
        for p in patterns:
            data.append((
                p.type, p.pattern, p.replace,
                1 if p.case_sensitive else 0,
                1 if p.enabled else 0,
                1 if p.applied else 0,
                p.name
            ))

        cur.executemany("""
                        INSERT INTO patterns (type, pattern, replacement, case_sensitive, enabled, applied, name)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, data)
        self.conn.commit()

    def get_patterns(self, pattern_type: str = None) -> List[PatternItem]:
        cur = self.conn.cursor()
        sql = "SELECT * FROM patterns"
        args = []
        if pattern_type:
            sql += " WHERE type = ?"
            args.append(pattern_type)

        cur.execute(sql, tuple(args))
        items = []
        for row in cur.fetchall():
            items.append(PatternItem(
                id=row['id'],
                pattern=row['pattern'],
                replace=row['replacement'],
                case_sensitive=bool(row['case_sensitive']),
                enabled=bool(row['enabled']),
                applied=bool(row['applied']),
                name=row['name'],
                type=row['type']
            ))
        return items

    # --- SETTINGS ---

    def set_setting(self, key: str, value: Any):
        val_str = str(value)
        val_type = 'str'

        if isinstance(value, bool):
            val_type = 'bool'
            val_str = '1' if value else '0'
        elif isinstance(value, int):
            val_type = 'int'
        elif isinstance(value, float):
            val_type = 'float'
        elif isinstance(value, (dict, list)):
            val_type = 'json'
            val_str = json.dumps(value)

        self.conn.execute("""
                          INSERT INTO settings (key, value, value_type)
                          VALUES (?, ?, ?) ON CONFLICT(key) DO
                          UPDATE SET value =excluded.value, value_type=excluded.value_type
                          """, (key, val_str, val_type))
        self.conn.commit()

    def get_setting(self, key: str, default=None) -> Any:
        cur = self.conn.execute("SELECT value, value_type FROM settings WHERE key = ?", (key,))
        res = cur.fetchone()
        if not res:
            return default

        val = res['value']
        dtype = res['value_type']

        try:
            if dtype == 'int': return int(val)
            if dtype == 'float': return float(val)
            if dtype == 'bool': return val == '1'
            if dtype == 'json': return json.loads(val)
            return val  # str
        except:
            return default