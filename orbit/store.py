"""SQLite incident store + incident memory + hash-chained audit log."""
import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path

_KEY = re.compile(r"(?i)password|token|secret|api[_-]?key|authorization")
_INLINE = re.compile(r"(?i)((?:password|token|secret|api[_-]?key|authorization)\s*[:=]\s*)(\"[^\"]*\"|\S+)")


def redact(o):
    """Scrub secrets from any JSON-able structure: by key name and by inline `key=value` text."""
    if isinstance(o, dict):
        return {k: "[REDACTED]" if _KEY.search(k) else redact(v) for k, v in o.items()}
    if isinstance(o, list):
        return [redact(v) for v in o]
    return _INLINE.sub(r"\1[REDACTED]", o) if isinstance(o, str) else o


class Store:
    # ponytail: SQLite + JSON blobs; Postgres per spec once multi-writer matters
    def __init__(self, path=":memory:", audit_path=None):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("create table if not exists incidents(id text primary key, data text)")
        self.db.execute("create table if not exists memory(incident_id text primary key, data text)")
        self.lock = threading.RLock()
        self.audit_path = Path(audit_path) if audit_path else None
        self.audit_log = []  # in-memory copy when no file
        self._prev = "0" * 64
        if self.audit_path and self.audit_path.exists():
            lines = self.audit_path.read_text().splitlines()
            if lines:
                self._prev = json.loads(lines[-1])["hash"]

    # incidents
    def create(self, **fields):
        with self.lock:
            n = self.db.execute("select count(*) from incidents").fetchone()[0] + 1
            inc = dict(id=f"INC-{n:04d}", status="DETECTED", final_status=None, evidence=[], hypotheses=[],
                       actions=[], recovery=[], timeline=[], approvals=[], root_cause=None, rca=None, **fields)
            self.db.execute("insert into incidents values(?,?)", (inc["id"], json.dumps(inc)))
            return inc

    def get(self, id):
        with self.lock:
            r = self.db.execute("select data from incidents where id=?", (id,)).fetchone()
        return json.loads(r[0]) if r else None

    def update(self, id, **fields):
        with self.lock:
            inc = self.get(id)
            inc.update(fields)
            self.db.execute("update incidents set data=? where id=?", (json.dumps(inc), id))
            return inc

    def list(self):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute("select data from incidents order by id desc")]

    # memory
    def remember(self, id, record):
        with self.lock:
            self.db.execute("insert or replace into memory values(?,?)", (id, json.dumps(record)))

    def similar(self, service, symptoms, k=3):
        """Jaccard over symptom tokens. ponytail: swap for Qdrant embeddings when memory is large."""
        with self.lock:
            rows = [json.loads(r[0]) for r in self.db.execute("select data from memory")]
        scored = []
        for r in rows:
            s = set(r["symptoms"])
            j = len(s & symptoms) / len(s | symptoms) if s | symptoms else 0
            scored.append((j + (0.1 if r["service"] == service else 0), r))
        return [dict(r, similarity=round(sc, 2)) for sc, r in sorted(scored, key=lambda x: -x[0])[:k] if sc >= 0.5]

    # audit
    def audit(self, **event):
        with self.lock:
            e = redact(dict(ts=time.time(), **json.loads(json.dumps(event, default=str))))
            body = json.dumps(e, sort_keys=True)
            h = hashlib.sha256((self._prev + body).encode()).hexdigest()
            line = json.dumps(dict(event=e, prev=self._prev, hash=h))
            self._prev = h
            self.audit_log.append(line)
            if self.audit_path:
                self.audit_path.parent.mkdir(parents=True, exist_ok=True)
                with self.audit_path.open("a") as f:
                    f.write(line + "\n")

    def audit_ok(self):
        prev = "0" * 64
        for line in self.audit_log:
            d = json.loads(line)
            body = json.dumps(d["event"], sort_keys=True)
            if d["prev"] != prev or hashlib.sha256((prev + body).encode()).hexdigest() != d["hash"]:
                return False
            prev = d["hash"]
        return True
