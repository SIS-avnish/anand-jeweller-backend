import sys
from pathlib import Path

from sqlalchemy import inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import engine
from models import QueueFeedback


def migrate():
    existing_tables = set(inspect(engine).get_table_names())
    if "queue_entries" not in existing_tables:
        raise RuntimeError(
            "queue_entries table is missing. Run the queue-system migration first."
        )

    QueueFeedback.__table__.create(bind=engine, checkfirst=True)
    feedback_columns = {
        column["name"] for column in inspect(engine).get_columns("queue_feedback")
    }
    column_statements = {
        "scheduled_at": "ALTER TABLE queue_feedback ADD COLUMN scheduled_at DATETIME",
        "processing_at": "ALTER TABLE queue_feedback ADD COLUMN processing_at DATETIME",
        "attempt_count": (
            "ALTER TABLE queue_feedback ADD COLUMN attempt_count INTEGER "
            "NOT NULL DEFAULT 0"
        ),
    }

    with engine.begin() as connection:
        for column_name, statement in column_statements.items():
            if column_name not in feedback_columns:
                connection.execute(text(statement))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_queue_feedback_scheduled_at "
            "ON queue_feedback (scheduled_at)"
        ))

    required = {"scheduled_at", "processing_at", "attempt_count"}
    migrated = {
        column["name"] for column in inspect(engine).get_columns("queue_feedback")
    }
    missing = required - migrated
    if missing:
        raise RuntimeError(f"Scheduled feedback migration missing: {sorted(missing)}")

    print("Scheduled feedback migration completed.")
    print("Verified scheduled_at, processing_at and attempt_count columns.")


if __name__ == "__main__":
    migrate()
