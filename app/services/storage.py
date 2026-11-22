from __future__ import annotations

import csv
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
