import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(root: Path):
    connection = sqlite3.connect(root / 'studio.sqlite3', timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'jobs').mkdir(exist_ok=True)
    with connect(root) as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin', 'subscriber'))
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL, modo TEXT NOT NULL DEFAULT 'voces' CHECK(modo IN ('voces', 'dialogo', 'voz')),
            ranges TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL DEFAULT '', created REAL NOT NULL, seconds REAL
        );
        ''')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(jobs)')}
        if 'modo' not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN modo TEXT NOT NULL DEFAULT 'voces'")
        if 'ranges' not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN ranges TEXT NOT NULL DEFAULT ''")
        # SQLite no permite ampliar el CHECK de modo: se recrea la tabla conservando los datos.
        table = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
        if table and "'voz'" not in (table['sql'] or ''):
            db.executescript('''
            CREATE TABLE jobs_voz (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                name TEXT NOT NULL, modo TEXT NOT NULL DEFAULT 'voces' CHECK(modo IN ('voces', 'dialogo', 'voz')),
                ranges TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '', created REAL NOT NULL, seconds REAL
            );
            INSERT INTO jobs_voz (id, user_id, name, modo, ranges, status, progress, message, created, seconds)
                SELECT id, user_id, name, modo, ranges, status, progress, message, created, seconds FROM jobs;
            DROP TABLE jobs;
            ALTER TABLE jobs_voz RENAME TO jobs;
            ''')
