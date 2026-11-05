"""SQLite storage. Hourly readings per lift.

Table readings: lift_id, ts (ISO 'YYYY-MM-DDTHH:00:00'), kwh, trips, door_cycles.
"The current moment" for every analysis is the latest timestamp in the DB,
so imported historical data works the same as live data.
"""
import os
import sqlite3

DB_PATH = os.environ.get(
    "LIFT_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.db")
)


def conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS lifts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS readings (
                lift_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                kwh REAL NOT NULL,
                trips INTEGER NOT NULL,
                door_cycles INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (lift_id, ts)
            );
            """
        )


def is_empty():
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 0


def clear():
    with conn() as c:
        c.execute("DELETE FROM readings")
        c.execute("DELETE FROM lifts")


def upsert_lift(lift_id, name=None):
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO lifts(id, name) VALUES (?, ?)", (lift_id, name or lift_id)
        )


def insert_readings(rows):
    """rows: iterable of (lift_id, ts, kwh, trips, door_cycles). Replaces on conflict."""
    with conn() as c:
        c.executemany(
            "INSERT OR REPLACE INTO readings(lift_id, ts, kwh, trips, door_cycles) "
            "VALUES (?,?,?,?,?)",
            list(rows),
        )


def add_to_hour(lift_id, ts, kwh, trips, door_cycles):
    """Accumulate live deltas into the hourly bucket (used by MQTT / Modbus ingest)."""
    upsert_lift(lift_id)
    with conn() as c:
        c.execute(
            "INSERT INTO readings(lift_id, ts, kwh, trips, door_cycles) VALUES (?,?,?,?,?) "
            "ON CONFLICT(lift_id, ts) DO UPDATE SET kwh=kwh+excluded.kwh, "
            "trips=trips+excluded.trips, door_cycles=door_cycles+excluded.door_cycles",
            (lift_id, ts, kwh, trips, door_cycles),
        )


def lifts():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT id, name FROM lifts ORDER BY id")]


def last_ts():
    with conn() as c:
        return c.execute("SELECT MAX(ts) FROM readings").fetchone()[0]


def readings(lift_id, since_ts):
    with conn() as c:
        cur = c.execute(
            "SELECT ts, kwh, trips, door_cycles FROM readings "
            "WHERE lift_id=? AND ts>=? ORDER BY ts",
            (lift_id, since_ts),
        )
        return [dict(r) for r in cur]


def merge_readings(rows, fields):
    """Import rows, replacing only the columns the file really contained.

    rows: (lift_id, ts, kwh, trips, door_cycles). fields: subset of {'kwh','trips','door_cycles'}.
    A file with only trips will not wipe energy that is already stored for the same hour."""
    cols = [f for f in ("kwh", "trips", "door_cycles") if f in fields]
    sets = ", ".join(f"{c}=excluded.{c}" for c in cols)
    with conn() as c:
        c.executemany(
            "INSERT INTO readings(lift_id, ts, kwh, trips, door_cycles) VALUES (?,?,?,?,?) "
            f"ON CONFLICT(lift_id, ts) DO UPDATE SET {sets}",
            list(rows),
        )


def rename_lift(lift_id, name):
    with conn() as c:
        cur = c.execute("UPDATE lifts SET name=? WHERE id=?", (name, lift_id))
        return cur.rowcount > 0


def delete_lift(lift_id):
    with conn() as c:
        c.execute("DELETE FROM readings WHERE lift_id=?", (lift_id,))
        cur = c.execute("DELETE FROM lifts WHERE id=?", (lift_id,))
        return cur.rowcount > 0


def all_readings(lift_id=None):
    with conn() as c:
        if lift_id:
            cur = c.execute("SELECT lift_id, ts, kwh, trips, door_cycles FROM readings WHERE lift_id=? ORDER BY ts", (lift_id,))
        else:
            cur = c.execute("SELECT lift_id, ts, kwh, trips, door_cycles FROM readings ORDER BY lift_id, ts")
        return [tuple(r) for r in cur]