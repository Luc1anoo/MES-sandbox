from sqlalchemy import inspect, text
from app.core import engine

columns_to_add = {
    "responsible_person": "VARCHAR(120) DEFAULT ''",
    "equipment_id": "INTEGER REFERENCES equipment(id) ON DELETE SET NULL",
    "tooling_requirement": "TEXT DEFAULT ''",
    "drawing_number": "VARCHAR(120) DEFAULT ''",
    "drawing_version": "VARCHAR(40) DEFAULT ''",
    "drawing_url": "TEXT DEFAULT ''",
    "sop_number": "VARCHAR(120) DEFAULT ''",
    "sop_version": "VARCHAR(40) DEFAULT ''",
    "sop_url": "TEXT DEFAULT ''",
}

table = "operation_card_versions"

with engine.begin() as conn:
    existing = {
        col["name"]
        for col in inspect(conn).get_columns(table)
    }

    for name, definition in columns_to_add.items():
        if name not in existing:
            conn.execute(text(
                f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'
            ))
            print(f"Added column: {name}")
        else:
            print(f"Already exists: {name}")

print("Migration completed.")
