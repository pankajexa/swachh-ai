import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

class Store:
    def __init__(self, root: Path):
        self.root = root
        self.media = root / 'media'
        self.media.mkdir(parents=True, exist_ok=True)
        self.db = root / 'swachh.db'
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS locations (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS inspections (id TEXT PRIMARY KEY, location_id TEXT NOT NULL, payload TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        with sqlite3.connect(self.db, timeout=15) as conn:
            yield conn

    def locations(self):
        with self.connect() as conn:
            return [json.loads(row[0]) for row in conn.execute('SELECT payload FROM locations ORDER BY rowid DESC')]

    def location(self, identifier):
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM locations WHERE id=?', (identifier,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_location(self, payload):
        with self.connect() as conn:
            conn.execute('INSERT INTO locations VALUES (?, ?)', (payload['id'], json.dumps(payload)))

    def save_inspection(self, payload):
        with self.connect() as conn:
            conn.execute('INSERT INTO inspections VALUES (?, ?, ?)', (payload['id'], payload['location_id'], json.dumps(payload)))

    def inspections(self, location_id):
        with self.connect() as conn:
            return [json.loads(row[0]) for row in conn.execute('SELECT payload FROM inspections WHERE location_id=? ORDER BY rowid DESC', (location_id,))]

    def inspection(self, identifier):
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM inspections WHERE id=?', (identifier,)).fetchone()
        return json.loads(row[0]) if row else None
