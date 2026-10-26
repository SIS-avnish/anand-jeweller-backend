import sys
from pathlib import Path

from sqlalchemy import inspect

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import engine
from models import ExternalFeedback, FeedbackSyncState


def migrate():
    ExternalFeedback.__table__.create(bind=engine, checkfirst=True)
    FeedbackSyncState.__table__.create(bind=engine, checkfirst=True)

    tables = set(inspect(engine).get_table_names())
    required = {"external_feedback", "feedback_sync_states"}
    missing = required - tables
    if missing:
        raise RuntimeError(f"Missing integration tables: {sorted(missing)}")

    print("CRE feedback integration migration completed.")
    print("Verified tables: external_feedback, feedback_sync_states")


if __name__ == "__main__":
    migrate()

