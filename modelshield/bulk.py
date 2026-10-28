"""Operator-issued chat allowances. Call under ChatService.lock in this process."""

import json
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator


class BulkPassInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    client_id: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=30, ge=1, le=30)
    minutes: int = Field(default=10, ge=1, le=60)
    concurrency: int = Field(default=2, ge=1, le=2)
    purpose: str = Field(min_length=3, max_length=160)

    @field_validator("purpose")
    @classmethod
    def purpose_required(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Describe the approved workload.")
        return value.strip()


class BulkPasses:
    def __init__(self, db):
        self.db = db
        db.execute("CREATE TABLE IF NOT EXISTS bulk_passes (id TEXT PRIMARY KEY, detail TEXT NOT NULL)")
        db.commit()
        self.records = {
            row[0]: json.loads(row[1])
            for row in db.execute("SELECT id, detail FROM bulk_passes").fetchall()
        }

    def save(self, record):
        self.db.execute(
            "INSERT INTO bulk_passes VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET detail=excluded.detail",
            (record["id"], json.dumps(record)),
        )
        self.db.commit()
        self.records[record["id"]] = record

    @staticmethod
    def view(record, now):
        status = (
            "revoked" if record["revoked_at"] is not None else
            "expired" if now >= record["expires_at"] else
            "exhausted" if record["used"] >= record["limit"] else "active"
        )
        return {**record, "status": status, "remaining": max(0, record["limit"] - record["used"])}

    def list(self, now):
        return [self.view(row, now) for row in sorted(
            self.records.values(), key=lambda row: row["issued_at"], reverse=True
        )]

    def current(self, key, now):
        return next((row for row in self.list(now) if row["client_id"] == key and
                     row["status"] in {"active", "exhausted"}), None)

    def issue(self, payload, now):
        if self.current(payload.client_id, now):
            raise HTTPException(409, "This client already has a pass. Revoke it or wait for expiry before issuing another.")
        record = {
            "id": "BULK-" + uuid4().hex, "client_id": payload.client_id,
            "limit": payload.limit, "used": 0, "concurrency": payload.concurrency,
            "purpose": payload.purpose, "issued_at": now,
            "expires_at": now + payload.minutes * 60, "revoked_at": None,
        }
        self.save(record)
        # Bound history, retaining every unexpired grant (including exhausted ones).
        old = [row for row in self.list(now) if row["status"] in {"expired", "revoked"}]
        for row in old[100:]:
            self.db.execute("DELETE FROM bulk_passes WHERE id = ?", (row["id"],))
            self.records.pop(row["id"], None)
        self.db.commit()
        return self.view(record, now)

    def revoke(self, pass_id, now):
        if pass_id not in self.records:
            raise HTTPException(404, "Unknown bulk pass.")
        record = {**self.records[pass_id]}
        if record["revoked_at"] is None:
            record["revoked_at"] = now
            self.save(record)
        return self.view(record, now)

    def check(self, pass_id, key, now, *, reserved=False):
        record = self.records.get(pass_id)
        if record is None or record["client_id"] != key:
            return "Bulk pass is not valid for this client."
        if record["revoked_at"] is not None:
            return "Bulk pass was revoked by the operator."
        if now >= record["expires_at"]:
            return "Bulk pass has expired."
        if not reserved and record["used"] >= record["limit"]:
            return "Bulk pass allowance is exhausted."
        return None

    def consume(self, pass_id, key, now):
        error = self.check(pass_id, key, now)
        if error:
            return None, error
        record = {**self.records[pass_id], "used": self.records[pass_id]["used"] + 1}
        self.save(record)
        return self.view(record, now), None
