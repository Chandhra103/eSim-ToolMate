from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_dir


class Storage:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or user_data_dir("eSim ToolMate", "FOSSEE"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "activity.sqlite3"
        self._init()

    def _init(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, timestamp TEXT, operation TEXT, tool TEXT, status TEXT, message TEXT, error TEXT)")
            connection.execute("CREATE TABLE IF NOT EXISTS configurations (id INTEGER PRIMARY KEY, timestamp TEXT, payload TEXT, action TEXT)")
            connection.execute("CREATE TABLE IF NOT EXISTS local_agents (device_id TEXT PRIMARY KEY, device_name TEXT NOT NULL, operating_system TEXT NOT NULL, architecture TEXT NOT NULL, os_release TEXT NOT NULL, token_hash TEXT NOT NULL, paired_at TEXT NOT NULL, last_seen TEXT, revoked INTEGER NOT NULL DEFAULT 0)")
            connection.execute("CREATE TABLE IF NOT EXISTS local_agent_reports (device_id TEXT PRIMARY KEY REFERENCES local_agents(device_id), scanned_at TEXT NOT NULL, payload TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS local_agent_operations (job_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, tool_id TEXT NOT NULL, operation TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, message TEXT NOT NULL DEFAULT '')")

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def pair_agent(self, device_id, device_name, operating_system, architecture, os_release, token_hash):
        timestamp = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "INSERT INTO local_agents(device_id,device_name,operating_system,architecture,os_release,token_hash,paired_at,last_seen,revoked) VALUES(?,?,?,?,?,?,?,?,0) "
                "ON CONFLICT(device_id) DO UPDATE SET device_name=excluded.device_name, operating_system=excluded.operating_system, architecture=excluded.architecture, os_release=excluded.os_release, token_hash=excluded.token_hash, paired_at=excluded.paired_at, last_seen=excluded.last_seen, revoked=0",
                (device_id, device_name, operating_system, architecture, os_release, token_hash, timestamp, timestamp),
            )
        return timestamp

    def local_agent_credentials(self, device_id):
        with sqlite3.connect(self.db) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT device_id,token_hash,revoked FROM local_agents WHERE device_id=?", (device_id,)).fetchone()
        return dict(row) if row else None

    def save_local_agent_report(self, device_id, report):
        scanned_at = report["scanned_at"]
        timestamp = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE local_agents SET last_seen=? WHERE device_id=?", (timestamp, device_id))
            connection.execute(
                "INSERT INTO local_agent_reports(device_id,scanned_at,payload) VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE SET scanned_at=excluded.scanned_at,payload=excluded.payload",
                (device_id, scanned_at, json.dumps(report, separators=(",", ":"), sort_keys=True)),
            )
        return timestamp

    def touch_local_agent(self, device_id):
        timestamp = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE local_agents SET last_seen=? WHERE device_id=? AND revoked=0", (timestamp, device_id))
        return timestamp

    def list_local_agents(self):
        with sqlite3.connect(self.db) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT a.device_id,a.device_name,a.operating_system,a.architecture,a.os_release,a.paired_at,a.last_seen,a.revoked,r.scanned_at,r.payload "
                "FROM local_agents a LEFT JOIN local_agent_reports r ON r.device_id=a.device_id ORDER BY a.paired_at DESC"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["report"] = json.loads(item.pop("payload")) if item.get("payload") else None
            result.append(item)
        return result

    def revoke_local_agent(self, device_id):
        with sqlite3.connect(self.db) as connection:
            cursor = connection.execute("UPDATE local_agents SET revoked=1 WHERE device_id=?", (device_id,))
            connection.execute(
                "UPDATE local_agent_operations SET status='canceled',updated_at=?,message='Device was revoked before this operation completed.' WHERE device_id=? AND status IN ('queued','awaiting_approval')",
                (datetime.now(UTC).isoformat(), device_id),
            )
        return cursor.rowcount > 0

    def log(self, operation, tool="System", status="info", message="", error=""):
        with sqlite3.connect(self.db) as connection:
            connection.execute("INSERT INTO activity(timestamp,operation,tool,status,message,error) VALUES(?,?,?,?,?,?)", (datetime.now(UTC).isoformat(), operation, tool, status, message, error))

    def recent(self, limit=50, query=""):
        with sqlite3.connect(self.db) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM activity WHERE message LIKE ? OR tool LIKE ? OR operation LIKE ? ORDER BY id DESC LIMIT ?", (f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
        return [dict(row) for row in rows]

    def export_csv(self, path):
        rows = self.recent(100000)
        with open(path, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=["id", "timestamp", "operation", "tool", "status", "message", "error"])
            writer.writeheader(); writer.writerows(rows)

    def clear(self):
        with sqlite3.connect(self.db) as connection: connection.execute("DELETE FROM activity")

    def save_config(self, config: dict, action="save"):
        payload = json.dumps(config, sort_keys=True)
        with sqlite3.connect(self.db) as connection: connection.execute("INSERT INTO configurations(timestamp,payload,action) VALUES(?,?,?)", (datetime.now(UTC).isoformat(), payload, action))
        self.log("configuration_change", status="success", message=f"Configuration {action}d")

    def current_config(self):
        with sqlite3.connect(self.db) as connection:
            row = connection.execute("SELECT payload FROM configurations ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else {}

    def config_history(self, limit=50):
        with sqlite3.connect(self.db) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT id,timestamp,action,payload FROM configurations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def backup(self, config: dict, path):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps({"created_at": datetime.now(UTC).isoformat(), "config": config}, indent=2), encoding="utf-8")
        temporary.replace(path)

    def restore(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data.get("config"), dict): raise ValueError("Invalid backup format")  # noqa: TRY004
        self.save_config(data["config"], "restore")
        return data["config"]

    def create_local_operation(self, job_id, device_id, tool_id, operation):
        timestamp = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "INSERT INTO local_agent_operations(job_id,device_id,tool_id,operation,status,created_at,updated_at,message) VALUES(?,?,?,?,?,?,?,?)",
                (job_id, device_id, tool_id, operation, "queued", timestamp, timestamp, "Waiting for the local agent."),
            )
        return {"job_id": job_id, "device_id": device_id, "tool_id": tool_id, "operation": operation, "status": "queued", "created_at": timestamp}

    def claim_local_operation(self, device_id, max_age_seconds=600):
        from datetime import timedelta

        now = datetime.now(UTC)
        cutoff = (now - timedelta(seconds=max_age_seconds)).isoformat()
        timestamp = now.isoformat()
        with sqlite3.connect(self.db, timeout=10) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE local_agent_operations SET status='expired',updated_at=?,message='Local approval window expired.' WHERE device_id=? AND status IN ('queued','awaiting_approval') AND created_at<?",
                (timestamp, device_id, cutoff),
            )
            row = connection.execute(
                "SELECT job_id,device_id,tool_id,operation,created_at FROM local_agent_operations WHERE device_id=? AND status='queued' ORDER BY created_at LIMIT 1",
                (device_id,),
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE local_agent_operations SET status='awaiting_approval',updated_at=?,message='Awaiting explicit approval on the managed computer.' WHERE job_id=? AND status='queued'",
                    (timestamp, row[0]),
                )
        if not row:
            return None
        return {"job_id": row[0], "device_id": row[1], "tool_id": row[2], "operation": row[3], "created_at": row[4], "status": "awaiting_approval"}

    def finish_local_operation(self, device_id, job_id, status, message):
        from datetime import timedelta

        now = datetime.now(UTC)
        timestamp = now.isoformat()
        cutoff = (now - timedelta(minutes=10)).isoformat()
        with sqlite3.connect(self.db) as connection:
            cursor = connection.execute(
                "UPDATE local_agent_operations SET status=?,updated_at=?,message=? WHERE job_id=? AND device_id=? AND status='awaiting_approval' AND created_at>=?",
                (status, timestamp, message[:4000], job_id, device_id, cutoff),
            )
        return cursor.rowcount == 1

    def local_operation_history(self, device_id, limit=50):
        with sqlite3.connect(self.db) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT job_id,tool_id,operation,status,created_at,updated_at,message FROM local_agent_operations WHERE device_id=? ORDER BY created_at DESC LIMIT ?",
                (device_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]
