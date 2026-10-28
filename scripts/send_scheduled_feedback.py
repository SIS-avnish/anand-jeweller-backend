import argparse
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import SessionLocal
from models import QueueFeedback
from queue_routes import _configured_feedback_url, _deliver_feedback_to_url


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Send individual WhatsApp feedback messages whose schedule is due."
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Keep running and check for due messages at a fixed interval.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Seconds between checks in daemon mode. Default: 60.",
    )
    return parser.parse_args()


def run_due_feedback(limit=100, delay=1.0, dry_run=False):
    db = SessionLocal()
    totals = {"due": 0, "queued": 0, "failed": 0, "skipped": 0}

    try:
        now_utc = datetime.utcnow()
        stale_before = now_utc - timedelta(minutes=30)

        # Recover a record if a previous worker stopped after claiming it.
        stale = db.query(QueueFeedback).filter(
            QueueFeedback.send_status == "processing",
            QueueFeedback.processing_at < stale_before,
            QueueFeedback.sent_at.is_(None),
        ).all()
        for feedback in stale:
            feedback.send_status = "pending"
            feedback.processing_at = None
        if stale:
            db.commit()

        due = (
            db.query(QueueFeedback)
            .filter(
                QueueFeedback.send_status == "pending",
                QueueFeedback.scheduled_at.isnot(None),
                QueueFeedback.scheduled_at <= now_utc,
                QueueFeedback.sent_at.is_(None),
                QueueFeedback.submitted_at.is_(None),
            )
            .order_by(QueueFeedback.scheduled_at.asc(), QueueFeedback.id.asc())
            .limit(max(limit, 1))
            .all()
        )
        totals["due"] = len(due)

        if dry_run:
            print({**totals, "dry_run": True, "checked_at_utc": now_utc.isoformat()})
            return totals

        for candidate in due:
            # Conditional update is the claim/lock. A second worker gets rowcount 0.
            claimed = db.query(QueueFeedback).filter(
                QueueFeedback.id == candidate.id,
                QueueFeedback.send_status == "pending",
                QueueFeedback.sent_at.is_(None),
            ).update({
                QueueFeedback.send_status: "processing",
                QueueFeedback.processing_at: datetime.utcnow(),
                QueueFeedback.attempt_count: QueueFeedback.attempt_count + 1,
            }, synchronize_session=False)
            db.commit()
            if not claimed:
                totals["skipped"] += 1
                continue

            feedback = db.query(QueueFeedback).filter(
                QueueFeedback.id == candidate.id
            ).first()
            entry = feedback.queue_entry
            url = _configured_feedback_url(feedback.token)
            if not url:
                feedback.send_status = "failed"
                feedback.processing_at = None
                feedback.provider_response = (
                    "FEEDBACK_STATIC_URL or FEEDBACK_BASE_URL is required"
                )
                db.commit()
                totals["failed"] += 1
                continue

            _, error = _deliver_feedback_to_url(db, entry, url)
            feedback = db.query(QueueFeedback).filter(
                QueueFeedback.id == candidate.id
            ).first()
            feedback.processing_at = None
            db.commit()

            if error:
                totals["failed"] += 1
            else:
                totals["queued"] += 1

            if delay > 0:
                time.sleep(delay)

        print({**totals, "checked_at_utc": now_utc.isoformat()})
        return totals
    finally:
        db.close()


if __name__ == "__main__":
    arguments = parse_arguments()
    if arguments.daemon and arguments.dry_run:
        raise SystemExit("--daemon and --dry-run cannot be used together")

    if arguments.daemon:
        interval = max(arguments.interval, 5)
        print({"status": "started", "mode": "daemon", "interval_seconds": interval})
        while True:
            started_at = time.monotonic()
            try:
                run_due_feedback(
                    limit=arguments.limit,
                    delay=max(arguments.delay, 0),
                )
            except Exception:
                # Keep the PM2 process alive after a temporary database/provider error.
                traceback.print_exc()
            elapsed = time.monotonic() - started_at
            time.sleep(max(interval - elapsed, 1))
    else:
        run_due_feedback(
            limit=arguments.limit,
            delay=max(arguments.delay, 0),
            dry_run=arguments.dry_run,
        )
