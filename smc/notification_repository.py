"""CHOCH-only notification ledger; schema initialization is explicit, never on import."""
from contextlib import closing
from pathlib import Path
import hashlib
import sqlite3
import uuid

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "smc_choch.db"
SCHEMA = """CREATE TABLE smc_notifications (
 signal_id TEXT PRIMARY KEY, message TEXT NOT NULL, retry_key TEXT NOT NULL,
 status TEXT NOT NULL, attempted_at TEXT NOT NULL, finished_at TEXT, error TEXT);
PRAGMA user_version=1;"""


def initialize(path=DEFAULT_PATH, apply=False):
    path = Path(path).resolve()
    if path.name != "smc_choch.db":
        raise ValueError("Initialization is restricted to the new smc_choch.db")
    if not apply:
        return dict(path=str(path), exists=path.exists(), sql=SCHEMA,
                    rollback="Archive the standalone CHOCH ledger; no existing database migration.")
    if path.exists():
        raise ValueError("Ledger already exists; initialization never overwrites a database")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path))) as db:
        db.executescript(SCHEMA)
        db.commit()
    return dict(path=str(path), initialized=True)


def attempted_ids(path=DEFAULT_PATH):
    if not Path(path).exists():
        return set()
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True)) as db:
        return {r[0] for r in db.execute("SELECT signal_id FROM smc_notifications")}


def reserve(preview, path=DEFAULT_PATH):
    """Atomically reserve the whole reviewed list before any external side effect."""
    if not Path(path).exists():
        raise ValueError("CHOCH notification ledger is not initialized")
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=rw", uri=True, timeout=30)) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            for ident, message in zip(preview["signal_ids"], preview["messages"]):
                key = str(uuid.uuid5(uuid.NAMESPACE_URL, "smc-choch:"+ident))
                db.execute("INSERT INTO smc_notifications VALUES (?,?,?,'PENDING',datetime('now'),NULL,NULL)",
                           (ident, message, key))
            db.commit()
        except Exception:
            db.rollback()
            raise


def finish(ident, ok, error, path=DEFAULT_PATH):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=rw", uri=True, timeout=30)) as db:
        db.execute("UPDATE smc_notifications SET status=?,finished_at=datetime('now'),error=? WHERE signal_id=?",
                   ("SENT" if ok else "UNCERTAIN", None if ok else error, ident))
        db.commit()


def snapshot_hash(frame):
    return hashlib.sha256(frame.to_json(date_format="iso").encode()).hexdigest()
