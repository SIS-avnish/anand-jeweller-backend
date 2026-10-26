import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from models import ExternalFeedback, FeedbackSyncState

load_dotenv()

CRE_API_BASE_URL = os.getenv("CRE_API_BASE_URL", "").rstrip("/")
CRE_INTEGRATION_KEY = os.getenv("CRE_INTEGRATION_KEY", "")


def _parse_datetime(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _integration_request(path: str, method: str = "GET") -> dict:
    if not CRE_API_BASE_URL or not CRE_INTEGRATION_KEY:
        raise RuntimeError("CRE integration credentials are not configured")

    request = Request(
        f"{CRE_API_BASE_URL}{path}",
        headers={
            "X-Integration-Key": CRE_INTEGRATION_KEY,
            "Accept": "application/json",
            "User-Agent": "anand-feedback-sync/1.0",
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"CRE API returned HTTP {response.status}")
            return json.loads(body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"CRE API HTTP {exc.code}: {body[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to connect to CRE API: {exc.reason}") from exc


def _sync_state(db: Session) -> FeedbackSyncState:
    state = db.query(FeedbackSyncState).filter(
        FeedbackSyncState.source_system == "cre"
    ).first()
    if not state:
        state = FeedbackSyncState(source_system="cre")
        db.add(state)
        db.flush()
    return state


def _upsert_feedback(db: Session, item: dict) -> ExternalFeedback:
    external_id = int(item["id"])
    feedback = db.query(ExternalFeedback).filter(
        ExternalFeedback.source_system == "cre",
        ExternalFeedback.external_feedback_id == external_id,
    ).first()
    if not feedback:
        feedback = ExternalFeedback(
            source_system="cre",
            external_feedback_id=external_id,
        )
        db.add(feedback)

    feedback.external_customer_id = item.get("walk_in_customer_id")
    feedback.visit_number = item.get("visit_number")
    feedback.customer_name = item.get("customer_name") or "Unknown customer"
    feedback.mobile_number = str(item.get("mobile_number") or "")
    feedback.external_store_id = item.get("store_id")
    feedback.store_name = item.get("store_name")
    feedback.rating = item.get("rating")
    feedback.comments = item.get("comments")
    feedback.send_status = item.get("send_status") or "pending"
    feedback.is_read = bool(item.get("is_read", False))
    feedback.submitted_at = _parse_datetime(item.get("submitted_at"))
    feedback.source_updated_at = (
        _parse_datetime(item.get("updated_at")) or datetime.utcnow()
    )
    feedback.synced_at = datetime.utcnow()
    return feedback


def sync_cre_feedback(db: Session, limit: int = 100) -> dict:
    state = _sync_state(db)
    imported = 0
    pages = 0

    try:
        while pages < 50:
            params = {"limit": limit}
            if state.cursor_time:
                params["after_time"] = state.cursor_time.isoformat()
                params["after_id"] = state.cursor_id

            payload = _integration_request(
                f"/api/integrations/feedback?{urlencode(params)}"
            )
            items = payload.get("items") or []
            for item in items:
                _upsert_feedback(db, item)
                imported += 1

            cursor = payload.get("next_cursor")
            if cursor:
                state.cursor_time = _parse_datetime(cursor.get("after_time"))
                state.cursor_id = int(cursor.get("after_id") or 0)

            db.commit()
            pages += 1

            if len(items) < limit or not cursor:
                break

        state.last_status = "success"
        state.last_error = None
        state.last_synced_at = datetime.utcnow()
        db.commit()
        return {
            "success": True,
            "imported": imported,
            "pages": pages,
            "last_synced_at": state.last_synced_at,
            "last_synced_at_ist": (
                state.last_synced_at + timedelta(hours=5, minutes=30)
            ),
        }
    except Exception as exc:
        db.rollback()
        state = _sync_state(db)
        state.last_status = "failed"
        state.last_error = str(exc)[:4000]
        db.commit()
        return {
            "success": False,
            "imported": imported,
            "error": str(exc),
        }


def resend_cre_feedback(external_feedback_id: int) -> dict:
    return _integration_request(
        f"/api/integrations/feedback/{external_feedback_id}/resend",
        method="POST",
    )

