"""SQLite audit trail. Never persist request text or credential secrets."""

import json
import sqlite3


class AuditStore:
    def __init__(self, path, retention=5000):
        if retention < 1:
            raise ValueError("Audit retention must be positive.")
        self.retention = retention
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at REAL NOT NULL, client_id TEXT NOT NULL, action TEXT NOT NULL, risk REAL NOT NULL, latency REAL NOT NULL, detail TEXT NOT NULL)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS events_at ON events(at)")
        self._prune()
        self.db.commit()

    def _prune(self):
        self.db.execute(
            "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
            (self.retention,),
        )

    def record(self, at, client_id, action, risk, latency, detail):
        self.db.execute(
            "INSERT INTO events(at, client_id, action, risk, latency, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (at, client_id, action, risk, latency, json.dumps(detail)),
        )
        self._prune()
        self.db.commit()

    def recent(self, limit=50):
        rows = self.db.execute(
            "SELECT id, at, client_id, action, risk, latency, detail FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "at": r[1],
                "client_id": r[2],
                "action": r[3],
                "risk": r[4],
                "latency": r[5],
                **json.loads(r[6]),
            }
            for r in rows
        ]

    def export(self):
        return self.recent(5000)

    def incident(self, incident_id):
        # The bounded audit is also the source for historical incident details.
        for event in self.export():
            if event.get("incident_id") == incident_id:
                return event
        return None

    def clear(self):
        self.db.execute("DELETE FROM events")
        self.db.commit()

    def close(self):
        self.db.close()
