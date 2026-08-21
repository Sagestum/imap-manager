"""Dauerhafte, taeglich aggregierte Sync-Statistik (Nachrichten pro Konto und Tag).

SQLite statt JSON, weil hier tatsaechlich nebenlaeufig gelesen/geschrieben wird: der Runner
schreibt sequentiell (ein Ordner-Mapping nach dem anderen), die Web-App liest ueber mehrere
Gunicorn-Worker gleichzeitig. Verbindungen werden pro Aufruf geoeffnet und geschlossen, nie
modulweit gehalten - Gunicorn forkt seine Worker, eine beim Import erzeugte Connection wuerde
ueber den Fork geteilt und das ist mit sqlite3 nicht sicher.
"""
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_FILENAME = "stats.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_stats (
    date TEXT NOT NULL,
    source_account TEXT NOT NULL,
    source_folder TEXT NOT NULL,
    dest_action TEXT NOT NULL,
    dest_folder TEXT NOT NULL,
    messages_transferred INTEGER NOT NULL DEFAULT 0,
    messages_deleted INTEGER NOT NULL DEFAULT 0,
    bytes_transferred INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    runs INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, source_account, source_folder, dest_action, dest_folder)
);

CREATE TABLE IF NOT EXISTS filter_state (
    dest_action TEXT NOT NULL,
    watch_folder TEXT NOT NULL,
    uidvalidity INTEGER NOT NULL,
    last_uid INTEGER NOT NULL,
    PRIMARY KEY (dest_action, watch_folder)
);
"""

# Auf den jeweiligen Label-Text verankert, damit z.B. "Messages transferred" nicht mit
# benachbarten Zeilen wie "Messages found in host1 not in host2" kollidiert. \s*:\s*(\d+) toleriert
# die wechselnde Leerzeichen-Polsterung von imapsync und ignoriert den "(N.NNN KiB)"-Anhang bei
# den Byte-Zeilen automatisch (nur die fuehrenden Ziffern werden erfasst).
_FIELD_PATTERNS = {
    "messages_transferred": re.compile(r"^Messages transferred\s*:\s*(\d+)", re.MULTILINE),
    "messages_deleted": re.compile(r"^Messages deleted on host1\s*:\s*(\d+)", re.MULTILINE),
    "bytes_transferred": re.compile(r"^Total bytes transferred\s*:\s*(\d+)", re.MULTILINE),
}
_ERRORS_RE = re.compile(r"^Detected (\d+) errors?", re.MULTILINE)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)  # SCHEMA enthaelt mehrere Statements, execute() erlaubt nur eins
    return conn


def parse_imapsync_output(output_text, returncode):
    """Liest messages_transferred/messages_deleted/bytes_transferred/errors aus der Ausgabe eines
    einzelnen imapsync-Aufrufs. Fehlt der Statistics-Block komplett (z.B. Absturz vor Sync-Start),
    bleiben die Zaehler 0 und errors wird auf 1 gesetzt, falls returncode != 0 war."""
    stats = {}
    for key, pattern in _FIELD_PATTERNS.items():
        match = pattern.search(output_text)
        stats[key] = int(match.group(1)) if match else 0

    errors_match = _ERRORS_RE.search(output_text)
    if errors_match:
        stats["errors"] = int(errors_match.group(1))
    else:
        stats["errors"] = 1 if returncode != 0 else 0

    return stats


def record_run(mapping, stats, db_path: Path):
    """Summiert die Statistik eines Laufs in die heutige (UTC-)Tageszeile ein. Nimmt aus mapping
    nur die Namen (nie Passwoerter oder sonstige Kontodaten), damit historische Zeilen auch nach
    dem Loeschen eines Kontos in der Konfiguration lesbar bleiben."""
    date = datetime.now(timezone.utc).date().isoformat()
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sync_stats (
                date, source_account, source_folder, dest_action, dest_folder,
                messages_transferred, messages_deleted, bytes_transferred, errors, runs
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT (date, source_account, source_folder, dest_action, dest_folder) DO UPDATE SET
                messages_transferred = messages_transferred + excluded.messages_transferred,
                messages_deleted     = messages_deleted + excluded.messages_deleted,
                bytes_transferred    = bytes_transferred + excluded.bytes_transferred,
                errors               = errors + excluded.errors,
                runs                 = runs + excluded.runs
            """,
            (
                date,
                mapping["source_account"]["name"],
                mapping["source_folder"],
                mapping["dest_action"]["name"],
                mapping["dest_folder"],
                stats["messages_transferred"],
                stats["messages_deleted"],
                stats["bytes_transferred"],
                stats["errors"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_filter_state(dest_action: str, watch_folder: str, db_path: Path):
    """Liefert (uidvalidity, last_uid) fuer den High-Water-Mark eines Filter-Ordners, oder
    (None, 0), falls dieser Ordner noch nie verarbeitet wurde."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT uidvalidity, last_uid FROM filter_state WHERE dest_action = ? AND watch_folder = ?",
            (dest_action, watch_folder),
        )
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, 0)
    finally:
        conn.close()


def set_filter_state(dest_action: str, watch_folder: str, uidvalidity: int, last_uid: int, db_path: Path):
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO filter_state (dest_action, watch_folder, uidvalidity, last_uid)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (dest_action, watch_folder) DO UPDATE SET
                uidvalidity = excluded.uidvalidity,
                last_uid    = excluded.last_uid
            """,
            (dest_action, watch_folder, uidvalidity, last_uid),
        )
        conn.commit()
    finally:
        conn.close()


def query_daily_by_account(days: int, db_path: Path):
    """Liefert pro (date, source_account) aufsummierte Zeilen (ueber alle Ordner hinweg) fuer die
    letzten `days` Tage. Gibt eine leere Liste zurueck, falls stats.db noch nicht existiert."""
    if not db_path.exists():
        return []

    since = (datetime.now(timezone.utc).date() - timedelta(days=days - 1)).isoformat()
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """
            SELECT date, source_account,
                   SUM(messages_transferred) AS messages_transferred,
                   SUM(messages_deleted) AS messages_deleted
            FROM sync_stats
            WHERE date >= ?
            GROUP BY date, source_account
            """,
            (since,),
        )
        return [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]
    finally:
        conn.close()
