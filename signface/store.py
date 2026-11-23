import contextlib
import hashlib
import json
import sqlite3
from pathlib import Path
from secrets import token_hex
from datetime import datetime, timezone

from image_lab.validation import Conflict, Invalid

from .model import identifier


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def key():
    return token_hex(10)


class Library:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.objects = self.root / "objects"
        self.objects.mkdir(exist_ok=True)
        self.database = self.root / "inspections.sqlite"
        with self.connection(write=True) as con:
            con.execute("CREATE TABLE IF NOT EXISTS parts (id TEXT PRIMARY KEY, document TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS readings (id TEXT PRIMARY KEY, part TEXT NOT NULL, document TEXT NOT NULL)")

    @contextlib.contextmanager
    def connection(self, write=False):
        con = sqlite3.connect(self.database, timeout=12, isolation_level=None)
        try:
            con.execute("PRAGMA busy_timeout=12000")
            if write:
                con.execute("BEGIN IMMEDIATE")
            yield con
            if write:
                con.commit()
        except BaseException:
            if write:
                con.rollback()
            raise
        finally:
            con.close()

    def put(self, data):
        sha = hashlib.sha256(data).hexdigest()
        dest = self.objects / sha
        if not dest.exists():
            temp = self.objects / ("write-" + key())
            try:
                temp.write_bytes(data)
                temp.replace(dest)
            finally:
                temp.unlink(missing_ok=True)
        return sha

    def object(self, sha):
        if not isinstance(sha, str) or len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise Invalid("Invalid image reference.")
        path = self.objects / sha
        if not path.is_file():
            raise Invalid("Image file is no longer available.")
        return path

    def create(self, data, captures=(), marks=()):
        doc = {**data, "id": key(), "revision": 1, "created_at": now(), "captures": list(captures), "marks": list(marks)}
        with self.connection(write=True) as con:
            con.execute("INSERT INTO parts values(?,?)", (doc["id"], json.dumps(doc)))
        return doc

    @staticmethod
    def load(con, table, ident):
        record = con.execute(f"SELECT document FROM {table} WHERE id=?", (identifier(ident),)).fetchone()
        if not record:
            raise Invalid("The requested record does not exist.")
        return json.loads(record[0])

    def parts(self):
        with self.connection() as con:
            return [json.loads(item[0]) for item in con.execute("SELECT document FROM parts ORDER BY rowid DESC LIMIT 120")]

    def part(self, ident):
        with self.connection() as con:
            return self.load(con, "parts", ident)

    def update(self, ident, version, apply):
        with self.connection(write=True) as con:
            doc = self.load(con, "parts", ident)
            if version != doc["revision"]:
                raise Conflict("The panel changed in another window. Refresh before editing.")
            apply(doc)
            doc["revision"] += 1
            con.execute("UPDATE parts SET document=? WHERE id=?", (json.dumps(doc), ident))
        return doc

    def save(self, part, data):
        doc = {**data, "id": key(), "part": part["id"], "revision": part["revision"], "created_at": now()}
        with self.connection(write=True) as con:
            live = self.load(con, "parts", part["id"])
            if live["revision"] != part["revision"]:
                raise Conflict("The capture or marks changed while the inspection was running. Run it again.")
            con.execute("INSERT INTO readings values(?,?,?)", (doc["id"], part["id"], json.dumps(doc)))
        return doc

    def reading(self, ident):
        with self.connection() as con:
            return self.load(con, "readings", ident)

    def readings(self, part):
        with self.connection() as con:
            return [json.loads(row[0]) for row in con.execute("SELECT document FROM readings WHERE part=? ORDER BY rowid DESC LIMIT 100", (identifier(part),))]
