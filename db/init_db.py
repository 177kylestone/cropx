from pathlib import Path
import sqlite3

DB_DIR = Path(__file__).parent
DB_PATH = DB_DIR / "cropx.db"
SCHEMA_PATH = DB_DIR / "schema.sql"


def initialize_database():
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")

        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        conn.executescript(schema_sql)
        conn.commit()

        print(f"Database initialized successfully at: {DB_PATH}")

    finally:
        conn.close()


if __name__ == "__main__":
    initialize_database()
