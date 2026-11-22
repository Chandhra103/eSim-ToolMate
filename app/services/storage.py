from __future__ import annotations

import csv
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_dir


class Storage:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or user_data_dir("eSim ToolMate", "FOSSEE")); self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "activity.sqlite3"; self._init()
    def _init(self):
        with sqlite3.connect(self.db) as c: c.execute("CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, timestamp TEXT, operation TEXT, tool TEXT, status TEXT, message TEXT, error TEXT)")
    def log(self, operation, tool="System", status="info", message="", error=""):
        with sqlite3.connect(self.db) as c: c.execute("INSERT INTO activity(timestamp,operation,tool,status,message,error) VALUES(?,?,?,?,?,?)", (datetime.now(UTC).isoformat(),operation,tool,status,message,error))
    def recent(self, limit=50, query=""):
        with sqlite3.connect(self.db) as c:
            c.row_factory=sqlite3.Row
            rows=c.execute("SELECT * FROM activity WHERE message LIKE ? OR tool LIKE ? ORDER BY id DESC LIMIT ?", (f"%{query}%",f"%{query}%",limit)).fetchall()
        return [dict(r) for r in rows]
    def export_csv(self, path):
        rows=self.recent(100000)
        with open(path,"w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=["id","timestamp","operation","tool","status","message","error"]); w.writeheader(); w.writerows(rows)
    def clear(self):
        with sqlite3.connect(self.db) as c: c.execute("DELETE FROM activity")
    def backup(self, config: dict, path):
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_suffix(p.suffix+".tmp"); tmp.write_text(json.dumps({"created_at":datetime.now(UTC).isoformat(),"config":config},indent=2),encoding="utf-8"); tmp.replace(p)
    def restore(self, path):
        data=json.loads(Path(path).read_text(encoding="utf-8"));
        if not isinstance(data.get("config"), dict): raise ValueError("Invalid backup format")  # noqa: TRY004
        return data["config"]
