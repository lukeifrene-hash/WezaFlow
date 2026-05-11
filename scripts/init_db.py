from __future__ import annotations

import sqlite3
from pathlib import Path


def init_db(root: Path | None = None) -> Path:
    repo_root = root or Path(__file__).resolve().parents[1]
    db_path = repo_root / "db" / "localflow.db"
    schema_path = repo_root / "db" / "schema.sql"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
    return db_path


if __name__ == "__main__":
    print(init_db())
