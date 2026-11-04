"""Локальный журнал событий боксов (SQLite) и интервалы занятости.

События - неизменяемый журнал (что и когда увидела система или поправил человек).
Интервалы занятости (occupancy) выводятся из событий: entry_confirmed открывает интервал,
exit_confirmed закрывает. Заказ-наряд НЕ закрывается: у одного ЗН может быть несколько
интервалов (тест-драйв, возврат, смена бокса).

Схема - предложенный контракт (см. CLAUDE_CODE_CAMERA_MVP_CONTEXT.md, раздел 6); поле
synced_at подготовлено под будущую идемпотентную отправку в облако.
"""

import sqlite3
import tomllib
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "captures" / "events.sqlite"

EVENT_TYPES = {
    "plate_observed",
    "entry_candidate",
    "entry_confirmed",
    "exit_candidate",
    "exit_confirmed",
    "manual_correction",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id         TEXT PRIMARY KEY,
    ts               TEXT NOT NULL,           -- ISO 8601 со смещением часового пояса
    camera_id        TEXT NOT NULL,
    bay_id           TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    plate_raw        TEXT,
    plate_normalized TEXT,
    ocr_confidence   REAL,
    track_id         TEXT,
    direction        TEXT,                    -- in / out
    snapshot_path    TEXT,
    work_order_id    TEXT,
    review_status    TEXT NOT NULL DEFAULT 'auto',   -- auto / needs_review / confirmed / corrected
    source           TEXT NOT NULL DEFAULT 'auto',   -- auto / manual
    note             TEXT,
    synced_at        TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_bay_ts ON events (bay_id, ts);

CREATE TABLE IF NOT EXISTS occupancy (
    interval_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    bay_id           TEXT NOT NULL,
    plate_normalized TEXT,
    started_at       TEXT NOT NULL,
    started_event_id TEXT NOT NULL,
    ended_at         TEXT,
    ended_event_id   TEXT,
    review_status    TEXT NOT NULL DEFAULT 'auto'
);
CREATE INDEX IF NOT EXISTS ix_occupancy_open ON occupancy (bay_id, ended_at);
"""


@dataclass
class Bay:
    id: str
    name: str
    camera_id: str
    enabled: bool


def load_config(path: Path = ROOT / "bays.toml") -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def record_event(
    conn: sqlite3.Connection,
    *,
    bay_id: str,
    camera_id: str,
    event_type: str,
    ts: str | None = None,
    plate_raw: str | None = None,
    plate_normalized: str | None = None,
    ocr_confidence: float | None = None,
    track_id: str | None = None,
    direction: str | None = None,
    snapshot_path: str | None = None,
    work_order_id: str | None = None,
    review_status: str = "auto",
    source: str = "auto",
    note: str | None = None,
    event_id: str | None = None,
) -> str:
    """Пишет событие и обновляет интервалы занятости. Повторный event_id игнорируется."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"неизвестный тип события: {event_type}")
    event_id = event_id or str(uuid.uuid4())
    ts = ts or now_iso()
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO events (event_id, ts, camera_id, bay_id, event_type, plate_raw,"
            " plate_normalized, ocr_confidence, track_id, direction, snapshot_path, work_order_id,"
            " review_status, source, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, ts, camera_id, bay_id, event_type, plate_raw, plate_normalized,
             ocr_confidence, track_id, direction, snapshot_path, work_order_id,
             review_status, source, note),
        )  # fmt: skip
        if cur.rowcount == 0:  # дубликат: идемпотентность
            return event_id
        if event_type == "entry_confirmed":
            _open_interval(conn, bay_id, plate_normalized, ts, event_id, review_status)
        elif event_type == "exit_confirmed":
            _close_interval(conn, bay_id, ts, event_id)
    return event_id


def _open_interval(conn, bay_id, plate, ts, event_id, review_status) -> None:
    still_open = conn.execute(
        "SELECT interval_id FROM occupancy WHERE bay_id = ? AND ended_at IS NULL", (bay_id,)
    ).fetchone()
    if still_open is not None:
        # Новый въезд, пока предыдущий не закрыт: не гадаем, отправляем на проверку.
        conn.execute(
            "UPDATE occupancy SET review_status = 'needs_review' WHERE interval_id = ?",
            (still_open["interval_id"],),
        )
        review_status = "needs_review"
    conn.execute(
        "INSERT INTO occupancy (bay_id, plate_normalized, started_at, started_event_id, review_status)"
        " VALUES (?,?,?,?,?)",
        (bay_id, plate, ts, event_id, review_status),
    )


def _close_interval(conn, bay_id, ts, event_id) -> None:
    row = conn.execute(
        "SELECT interval_id FROM occupancy WHERE bay_id = ? AND ended_at IS NULL"
        " ORDER BY started_at DESC LIMIT 1",
        (bay_id,),
    ).fetchone()
    if row is None:
        return  # выезд без открытого интервала - событие остаётся в журнале для разбора
    conn.execute(
        "UPDATE occupancy SET ended_at = ?, ended_event_id = ? WHERE interval_id = ?",
        (ts, event_id, row["interval_id"]),
    )


def bay_state(conn: sqlite3.Connection, bay_id: str) -> dict:
    """EMPTY / OCCUPIED / REVIEW по открытому интервалу."""
    row = conn.execute(
        "SELECT * FROM occupancy WHERE bay_id = ? AND ended_at IS NULL"
        " ORDER BY started_at DESC LIMIT 1",
        (bay_id,),
    ).fetchone()
    if row is None:
        return {"bay_id": bay_id, "state": "EMPTY"}
    state = "REVIEW" if row["review_status"] == "needs_review" else "OCCUPIED"
    return {
        "bay_id": bay_id,
        "state": state,
        "plate": row["plate_normalized"],
        "since": row["started_at"],
    }
