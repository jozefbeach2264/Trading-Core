# File: inspect_memory_tracker_db.py
import sqlite3
import json
from pprint import pprint

DB_PATH = "logs/memory_tracker.db"

def check_table(table_name):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"✅ {table_name} rows: {count}")

        if count > 0:
            cursor.execute(f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT 3")
            rows = cursor.fetchall()
            print(f"\n📌 Last 3 rows from {table_name}:")
            for row in rows:
                print("-" * 40)
                pprint(row)
        else:
            print(f"⚠️ No entries in {table_name}\n")

def main():
    print("=== Memory Tracker DB Inspection ===")
    for table in ["filters", "trades", "verdicts"]:
        check_table(table)

if __name__ == "__main__":
    main()