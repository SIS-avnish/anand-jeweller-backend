import csv
import html
import io
import json
import os
import secrets
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import random
import re
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
import bcrypt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, status, UploadFile
from dotenv import load_dotenv
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import desc, text
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db, engine
from jwt_auth import require_admin_auth
from auth import authenticate_user, login_user, is_authenticated
from cre_feedback_sync import resend_cre_feedback, sync_cre_feedback
from models import AdminUser, ExternalFeedback, QueueEntry, QueueFeedback, Store, UserRole

load_dotenv()

router = APIRouter()
templates = Jinja2Templates(directory=['templates', '.'])
CITY_PREFIXES = {'Indore': 'IND', 'Bhopal': 'BHP', 'Raipur': 'RAI'}

# Ensure upload directory for queue documents exists
UPLOAD_DIR = os.path.join("static", "uploads", "queue")
os.makedirs(UPLOAD_DIR, exist_ok=True)
MAX_IMAGE_DIMENSION = 2000


KIT19_WHATSAPP_URL = os.getenv("KIT19_WHATSAPP_URL", "https://services.kit19.com/IMS/Whatsapp/Template")
KIT19_WHATSAPP_KEY = os.getenv("KIT19_WHATSAPP_KEY", "")
KIT19_WHATSAPP_USERNAME = os.getenv("KIT19_WHATSAPP_USERNAME", "")
FEEDBACK_BASE_URL = os.getenv("FEEDBACK_BASE_URL", "").rstrip("/")
FEEDBACK_STATIC_URL = os.getenv("FEEDBACK_STATIC_URL", "").strip()
FEEDBACK_IMMEDIATE_SEND = os.getenv("FEEDBACK_IMMEDIATE_SEND", "false").strip().lower() in ("1", "true", "yes", "on")
try:
    FEEDBACK_DELAY_HOURS = max(float(os.getenv("FEEDBACK_DELAY_HOURS", "5")), 0)
except ValueError:
    FEEDBACK_DELAY_HOURS = 5.0


class FeedbackSubmission(BaseModel):
    token: str = Field(min_length=10, max_length=100)
    rating: int = Field(ge=1, le=5)
    comments: Optional[str] = Field(default=None, max_length=2000)

def _auto_migrate_queue_entry_columns():
    """Ensure aadhar_image and pan_image columns exist in SQLite queue_entries table"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(queue_entries)"))
            columns = [row[1] for row in result.fetchall()]
            if "aadhar_image" not in columns:
                conn.execute(text("ALTER TABLE queue_entries ADD COLUMN aadhar_image VARCHAR"))
                conn.commit()
            if "pan_image" not in columns:
                conn.execute(text("ALTER TABLE queue_entries ADD COLUMN pan_image VARCHAR"))
                conn.commit()
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_queue_entries_registration_lookup "
                "ON queue_entries (mobile_number, store_id, status, created_at)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_queue_entries_city_created_at "
                "ON queue_entries (city, created_at)"
            ))
            conn.commit()
    except Exception as e:
        print(f"Auto-migration check notice: {e}")

_auto_migrate_queue_entry_columns()


def _save_uploaded_file(file: Optional[UploadFile], prefix: str) -> Optional[str]:
    """Helper to save uploaded document file, automatically converting images to WebP format"""
    if not file or not file.filename:
        return None
    contents = file.file.read()
    if not contents:
        return None

    # Automatically convert uploaded images to WEBP format
    try:
        import io
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(contents))
        if img.format == "JPEG":
            img.draft("RGB", (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))
        img = ImageOps.exif_transpose(img)
        filename = f"{prefix}_{uuid.uuid4().hex[:10]}.webp"
        filepath = os.path.join(UPLOAD_DIR, filename)

        if max(img.size) > MAX_IMAGE_DIMENSION:
            img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)

        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

        img.save(filepath, "WEBP", quality=80, method=3)
        return f"/static/uploads/queue/{filename}"
    except Exception as e:
        print(f"[Notice] Image WebP conversion notice: {e}, saving raw file")

    file_ext = os.path.splitext(file.filename)[1].lower() or ".jpg"
    filename = f"{prefix}_{uuid.uuid4().hex[:10]}{file_ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(contents)
    return f"/static/uploads/queue/{filename}"


def _optional_int(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _queue_query(city: Optional[str] = None, store_id: Optional[int] = None) -> str:
    params = {}
    if city:
        params['city'] = city
    if store_id is not None:
        params['store_id'] = store_id
    return f"?{urlencode(params)}" if params else ""


def _group(stores):
    grouped = defaultdict(list)
    for store in stores:
        grouped[store.city or 'Indore'].append(store)
    return dict(sorted(grouped.items(), key=lambda x: x[0].lower()))


def _code(city):
    city = (city or '').strip()
    if city in CITY_PREFIXES:
        return CITY_PREFIXES[city]
    clean = re.sub(r'[^A-Za-z0-9]', '', city).upper()
    return (clean[:3] or 'Q')[:3]


def _mobile(value):
    return re.sub(r'\D', '', value or '')


def _whatsapp_mobile(value: str) -> str:
    mobile = _mobile(value)
    if len(mobile) == 10:
        return f"91{mobile}"
    if len(mobile) == 12 and mobile.startswith("91"):
        return mobile
    raise ValueError("Visitor mobile number must be a valid Indian WhatsApp number")


def _configured_feedback_url(token: str) -> Optional[str]:
    if FEEDBACK_STATIC_URL:
        if "{token}" in FEEDBACK_STATIC_URL:
            return FEEDBACK_STATIC_URL.replace("{token}", token)
        separator = "&" if "?" in FEEDBACK_STATIC_URL else "?"
        return f"{FEEDBACK_STATIC_URL}{separator}token={token}"
    if FEEDBACK_BASE_URL:
        return f"{FEEDBACK_BASE_URL}/feedback/{token}"
    return None


def _feedback_url(request: Request, token: str) -> str:
    return _configured_feedback_url(token) or str(
        request.url_for("feedback_form", token=token)
    )


def _send_feedback_whatsapp(entry: QueueEntry, feedback_url: str) -> tuple[str, str]:
    if not KIT19_WHATSAPP_KEY or not KIT19_WHATSAPP_USERNAME:
        raise RuntimeError("Kit19 WhatsApp credentials are not configured")

    recipient = _whatsapp_mobile(entry.mobile_number)
    payload = {
        "key": KIT19_WHATSAPP_KEY,
        "username": KIT19_WHATSAPP_USERNAME,
        "name": "whatsapp",
        "remarks": (
            "Dear Customer,\n\nYour feedback ensures we continually improve. \n\n"
            "Please click below to share your thoughts on your recent visit at our store.\n"
            "*[@CustomField1@]*\n\nThank you in advance!\n\nRegards,\n*Anand Jewels*"
        ),
        "whatsapp": {
            "to": recipient,
            "type": "template",
            "category": "UTILITY",
            "recipient_type": "individual",
            "template": {
                "namespace": "",
                "language": {"policy": "deterministic", "code": "en"},
                "name": "feedback_template",
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": feedback_url}],
                }],
            },
        },
    }
    provider_request = UrlRequest(
        KIT19_WHATSAPP_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "curl/8.10.1",
        },
        method="POST",
    )
    try:
        with urlopen(provider_request, timeout=15) as response:
            response_text = response.read().decode("utf-8", errors="replace")
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"WhatsApp API returned HTTP {response.status}")
            return recipient, response_text[:4000]
    except HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WhatsApp API returned HTTP {exc.code}: {response_text[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to connect to WhatsApp API: {exc.reason}") from exc




def _ensure_feedback(db: Session, entry: QueueEntry) -> QueueFeedback:
    feedback = db.query(QueueFeedback).filter(
        QueueFeedback.queue_entry_id == entry.id
    ).first()
    if not feedback:
        feedback = QueueFeedback(
            queue_entry_id=entry.id,
            token=secrets.token_urlsafe(32),
            send_status="pending",
            # QueueEntry.created_at and all persisted timestamps use UTC.
            # Adding elapsed hours here produces the same instant as adding them in IST.
            scheduled_at=datetime.utcnow() + timedelta(hours=FEEDBACK_DELAY_HOURS),
        )
        db.add(feedback)
        db.flush()
    return feedback


def _deliver_feedback_to_url(
    db: Session,
    entry: QueueEntry,
    feedback_url: str,
) -> tuple[QueueFeedback, Optional[str]]:
    feedback = _ensure_feedback(db, entry)

    try:
        recipient, provider_response = _send_feedback_whatsapp(entry, feedback_url)
        provider_data = json.loads(provider_response)
        if provider_data.get("success") is not True:
            raise RuntimeError("Kit19 did not accept the WhatsApp message")
        feedback.sent_to = recipient
        feedback.send_status = "queued"
        feedback.provider_response = provider_response
        feedback.sent_at = datetime.utcnow()
        error = None
    except Exception as exc:
        feedback.send_status = "failed"
        feedback.provider_response = str(exc)[:4000]
        error = str(exc)

    db.commit()
    db.refresh(feedback)
    return feedback, error


def _deliver_feedback(
    db: Session,
    request: Request,
    entry: QueueEntry,
) -> tuple[QueueFeedback, Optional[str]]:
    feedback = _ensure_feedback(db, entry)
    return _deliver_feedback_to_url(
        db,
        entry,
        _feedback_url(request, feedback.token),
    )
def _token(db: Session, city: str) -> str:
    # Calculate current IST time (UTC + 5:30)
    now_utc = datetime.utcnow()
    now_ist = now_utc + timedelta(hours=5, minutes=30)
    
    # Calculate 12:00 AM IST midnight start boundary in UTC
    ist_midnight_today = datetime(now_ist.year, now_ist.month, now_ist.day)
    start_of_day_utc = ist_midnight_today - timedelta(hours=5, minutes=30)
    end_of_day_utc = start_of_day_utc + timedelta(days=1)
    
    # Count entries created today (since 12 AM IST) for this city
    today_count = db.query(QueueEntry).filter(
        QueueEntry.city == city,
        QueueEntry.created_at >= start_of_day_utc,
        QueueEntry.created_at < end_of_day_utc,
    ).count()
    
    return f"{_code(city)}-{today_count + 1:03d}"





@router.get('/queue/register', response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(get_db), city: Optional[str] = None, store_id: Optional[int] = None):
    stores = db.query(Store).order_by(Store.city.asc(), Store.store_name.asc()).all()
    grouped = _group(stores)
    
    # 1. Determine requested city from `city` query param or standalone query flag (e.g., ?raipur, ?indore, ?bhopal)
    requested_city = city
    if not requested_city:
        for key in request.query_params.keys():
            if key and key.lower() not in ('store_id', 'search'):
                requested_city = key
                break

    # 2. Match case-insensitively with available cities in database
    selected_city = ''
    if requested_city:
        req_clean = requested_city.strip().lower()
        for available_city in grouped.keys():
            if available_city.lower() == req_clean:
                selected_city = available_city
                break

    if not selected_city:
        selected_city = 'Indore' if 'Indore' in grouped else next(iter(grouped.keys()), '')

    return templates.TemplateResponse('queue_register.html', {
        'request': request,
        'stores_by_city': grouped,
        'cities': list(grouped.keys()),
        'selected_city': selected_city,
        'selected_store_id': int(store_id) if store_id else '',
    })


@router.post('/queue/register')
def register_visitor(
    request: Request,
    city: str = Form(...),
    store_id: int = Form(...),
    name: str = Form(...),
    address: str = Form(''),
    mobile_number: str = Form(...),
    email: str = Form(''),
    aadhar_number: str = Form(''),
    aadhar_image: Optional[UploadFile] = File(None),
    pan_number: str = Form(''),
    pan_image: Optional[UploadFile] = File(None),
    captcha_answer: str = Form(...),
    captcha_expected: str = Form(...),
    db: Session = Depends(get_db),
):
    stores = db.query(Store).order_by(Store.city.asc(), Store.store_name.asc()).all()
    grouped = _group(stores)
    store = db.query(Store).filter(Store.id == store_id).first()

    def error(msg):
        return templates.TemplateResponse('queue_register.html', {
            'request': request,
            'stores_by_city': grouped,
            'cities': list(grouped.keys()),
            'selected_city': city,
            'selected_store_id': store_id,
            'error': msg,
            'form_data': {
                'name': name,
                'mobile_number': mobile_number,
                'address': address,
                'email': email,
                'aadhar_number': aadhar_number,
                'pan_number': pan_number
            },
        })
    if captcha_answer != captcha_expected:
        return error('Security check failed. Incorrect math calculation.')

    if not store or store.city != city:
        return error('Please choose a valid store for the selected city.')

    mobile = _mobile(mobile_number)
    if len(mobile) != 10:
        return error('Please enter a valid 10-digit mobile number.')
    if len(name.strip()) < 2:
        return error('Please enter the visitor name.')

    # Check for existing registration within the last 30 minutes for this mobile at this store
    thirty_mins_ago_utc = datetime.utcnow() - timedelta(minutes=30)
    existing_entry = db.query(QueueEntry).filter(
        QueueEntry.mobile_number == mobile,
        QueueEntry.store_id == store.id,
        QueueEntry.created_at >= thirty_mins_ago_utc,
        QueueEntry.status == 'open'
    ).order_by(QueueEntry.created_at.desc()).first()

    if existing_entry:
        if existing_entry.created_at:
            ist_created_at = existing_entry.created_at + timedelta(hours=5, minutes=30)
            time_str = ist_created_at.strftime('%I:%M %p on %d %b %Y')
        else:
            time_str = "recently"
        msg = f"Your number is already registered in Queue at {time_str}. You can submit another request after 30 mins."
        request.session['queue_last_entry_id'] = existing_entry.id
        request.session['queue_message'] = msg
        return RedirectResponse(url='/queue/success', status_code=302)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="queue-image") as executor:
        upload_jobs = [
            executor.submit(_save_uploaded_file, aadhar_image, "aadhar"),
            executor.submit(_save_uploaded_file, pan_image, "pan"),
        ]
        aadhar_img_url, pan_img_url = [job.result() for job in upload_jobs]

    entry = QueueEntry(
        store_id=store.id,
        city=city,
        name=name.strip(),
        address=address.strip() or None,
        mobile_number=mobile,
        email=email.strip() or None,
        aadhar_number=aadhar_number.strip() or None,
        pan_number=pan_number.strip() or None,
        aadhar_image=aadhar_img_url,
        pan_image=pan_img_url,
        status='open',
        token=_token(db, city),
    )
    db.add(entry)
    db.flush()
    feedback = _ensure_feedback(db, entry)
    db.commit()
    db.refresh(entry)

    if FEEDBACK_IMMEDIATE_SEND:
        feedback, feedback_error = _deliver_feedback(db, request, entry)
        if feedback_error:
            request.session['queue_feedback_error'] = (
                f'Queue registered, but WhatsApp message failed: {feedback_error}'
            )
        else:
            request.session['queue_feedback_message'] = (
                'Feedback link queued for WhatsApp delivery.'
            )
    else:
        scheduled_at_ist = (
            feedback.scheduled_at + timedelta(hours=5, minutes=30)
            if feedback.scheduled_at else None
        )
        request.session['queue_feedback_message'] = (
            'Feedback link scheduled for WhatsApp at '
            f'{scheduled_at_ist.strftime("%I:%M %p on %d %b %Y")} IST.'
        )
    request.session['queue_last_entry_id'] = entry.id
    return RedirectResponse(url='/queue/success', status_code=302)


@router.get('/queue/success', response_class=HTMLResponse)
async def success_page(request: Request, db: Session = Depends(get_db)):
    entry_id = request.session.get('queue_last_entry_id')
    queue_message = request.session.pop('queue_message', None)
    queue_feedback_message = request.session.pop('queue_feedback_message', None)
    queue_feedback_error = request.session.pop('queue_feedback_error', None)

    if not entry_id:
        return RedirectResponse(url='/queue/register', status_code=302)
    entry = db.query(QueueEntry).filter(QueueEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse(url='/queue/register', status_code=302)
    store = db.query(Store).filter(Store.id == entry.store_id).first()
    ist_created_at = (entry.created_at + timedelta(hours=5, minutes=30)) if entry.created_at else datetime.now()
    return templates.TemplateResponse('queue_success.html', {
        'request': request,
        'entry': entry,
        'store': store,
        'ist_created_at': ist_created_at,
        'queue_message': queue_message,
        'queue_feedback_message': queue_feedback_message,
        'queue_feedback_error': queue_feedback_error,
    })


from sqlalchemy import desc, or_, text

@router.get('/admin/queue', response_class=HTMLResponse)
async def queue_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth),
    city: Optional[str] = None,
    store_id: Optional[str] = None,
    search: Optional[str] = None,
    active_page: int = 1,
    closed_page: int = 1,
    per_page: int = 10,
    tab: str = 'active',
):
    stores = db.query(Store).order_by(Store.city.asc(), Store.store_name.asc()).all()
    selected_store_id = _optional_int(store_id)
    search_clean = (search or '').strip()
    per_page = per_page if per_page in (10, 25, 50, 100) else 10
    active_page = max(active_page, 1)
    closed_page = max(closed_page, 1)
    selected_tab = 'closed' if tab == 'closed' else 'active'

    if current_user.role == UserRole.STORE_ADMIN.value:
        if not current_user.store_id:
            raise HTTPException(status_code=403, detail='Store admin is not linked to a store')
        store = db.query(Store).filter(Store.id == current_user.store_id).first()
        expected_city = store.city if store else ""
        expected_store_id = current_user.store_id
        if request.query_params.get('city') != expected_city or request.query_params.get('store_id') != str(expected_store_id):
            redirect_url = f"/admin/queue?city={expected_city}&store_id={expected_store_id}"
            if search_clean:
                redirect_url += f"&search={urlencode({'search': search_clean})[7:]}"
            return RedirectResponse(url=redirect_url, status_code=302)
        city = expected_city
        selected_store_id = expected_store_id
        stores = [store] if store else []
    grouped = _group([s for s in stores if s])
    base_query = db.query(QueueEntry)
    if city:
        base_query = base_query.filter(QueueEntry.city == city)
    if selected_store_id is not None:
        base_query = base_query.filter(QueueEntry.store_id == selected_store_id)
    if search_clean:
        term = f"%{search_clean}%"
        base_query = base_query.filter(
            or_(
                QueueEntry.name.ilike(term),
                QueueEntry.mobile_number.ilike(term),
                QueueEntry.aadhar_number.ilike(term),
                QueueEntry.pan_number.ilike(term),
                QueueEntry.token.ilike(term),
            )
        )
    if current_user.role == UserRole.STORE_ADMIN.value:
        base_query = base_query.filter(QueueEntry.store_id == current_user.store_id)

    active_query = base_query.filter(QueueEntry.status == 'open')
    closed_query = base_query.filter(QueueEntry.status == 'closed')
    active_total = active_query.count()
    closed_total = closed_query.count()
    active_pages = max(1, (active_total + per_page - 1) // per_page)
    closed_pages = max(1, (closed_total + per_page - 1) // per_page)
    active_page = min(active_page, active_pages)
    closed_page = min(closed_page, closed_pages)
    active_entries = (
        active_query.order_by(desc(QueueEntry.created_at))
        .offset((active_page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    closed_entries = (
        closed_query.order_by(desc(QueueEntry.created_at))
        .offset((closed_page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    def pagination_url(target_tab: str, target_page: int) -> str:
        params = {
            'city': city or '',
            'store_id': selected_store_id or '',
            'search': search_clean,
            'active_page': target_page if target_tab == 'active' else active_page,
            'closed_page': target_page if target_tab == 'closed' else closed_page,
            'per_page': per_page,
            'tab': target_tab,
        }
        return f"/admin/queue?{urlencode(params)}"

    def pagination_items(target_tab: str, current_page: int, total_pages: int):
        if total_pages <= 7:
            page_numbers = list(range(1, total_pages + 1))
        else:
            visible_pages = {
                1, 2, 3,
                current_page - 1, current_page, current_page + 1,
                total_pages - 1, total_pages,
            }
            page_numbers = sorted(page for page in visible_pages if 1 <= page <= total_pages)

        items = []
        previous_page = None
        for page_number in page_numbers:
            if previous_page is not None and page_number - previous_page > 1:
                items.append(None)
            items.append({
                'page': page_number,
                'url': pagination_url(target_tab, page_number),
                'current': page_number == current_page,
            })
            previous_page = page_number
        return items

    active_pagination = {
        'page': active_page,
        'pages': active_pages,
        'total': active_total,
        'previous_url': pagination_url('active', active_page - 1) if active_page > 1 else None,
        'next_url': pagination_url('active', active_page + 1) if active_page < active_pages else None,
        'page_items': pagination_items('active', active_page, active_pages),
    }
    closed_pagination = {
        'page': closed_page,
        'pages': closed_pages,
        'total': closed_total,
        'previous_url': pagination_url('closed', closed_page - 1) if closed_page > 1 else None,
        'next_url': pagination_url('closed', closed_page + 1) if closed_page < closed_pages else None,
        'page_items': pagination_items('closed', closed_page, closed_pages),
    }

    # Calculate Today's Visitor Statistics (12 AM IST Reset)
    now_utc = datetime.utcnow()
    now_ist = now_utc + timedelta(hours=5, minutes=30)
    ist_midnight_today = datetime(now_ist.year, now_ist.month, now_ist.day)
    start_of_day_utc = ist_midnight_today - timedelta(hours=5, minutes=30)
    end_of_day_utc = start_of_day_utc + timedelta(days=1)

    today_total_visitors = base_query.filter(
        QueueEntry.created_at >= start_of_day_utc,
        QueueEntry.created_at < end_of_day_utc
    ).count()
    today_active_count = base_query.filter(
        QueueEntry.status == 'open',
        QueueEntry.created_at >= start_of_day_utc,
        QueueEntry.created_at < end_of_day_utc
    ).count()
    today_completed_count = base_query.filter(
        QueueEntry.status == 'closed',
        QueueEntry.created_at >= start_of_day_utc,
        QueueEntry.created_at < end_of_day_utc
    ).count()
    all_time_total_count = base_query.count()

    admins = []
    if current_user.role == UserRole.SUPER_ADMIN.value:
        admins = db.query(AdminUser).filter(AdminUser.role == UserRole.STORE_ADMIN.value).order_by(AdminUser.created_at.desc()).all()
    
    assigned_store = None
    if current_user.role == UserRole.STORE_ADMIN.value and current_user.store_id:
        assigned_store = db.query(Store).filter(Store.id == current_user.store_id).first()
    feedback_message = request.session.pop("feedback_message", None)
    feedback_error = request.session.pop("feedback_error", None)


    return templates.TemplateResponse('queue_dashboard.html', {
        'request': request,
        'user': current_user,
        'user_role': current_user.role,
        'assigned_store': assigned_store,
        'stores_by_city': grouped,
        'cities': list(grouped.keys()),
        'selected_city': city or '',
        'selected_store_id': selected_store_id or '',
        'search_query': search_clean,
        'active_entries': active_entries,
        'closed_entries': closed_entries,
        'active_pagination': active_pagination,
        'closed_pagination': closed_pagination,
        'per_page': per_page,
        'selected_tab': selected_tab,
        'today_total_visitors': today_total_visitors,
        'today_active_count': today_active_count,
        'today_completed_count': today_completed_count,
        'all_time_total_count': all_time_total_count,
        'admins': admins,
        'is_super_admin': current_user.role == UserRole.SUPER_ADMIN.value,
        'is_store_admin': current_user.role == UserRole.STORE_ADMIN.value,
        'feedback_message': feedback_message,
        'feedback_error': feedback_error,
    })


@router.get('/feedback/{token}', response_class=HTMLResponse, name='feedback_form')
async def feedback_form(request: Request, token: str, db: Session = Depends(get_db)):
    feedback = db.query(QueueFeedback).filter(QueueFeedback.token == token).first()
    if not feedback:
        raise HTTPException(status_code=404, detail='Feedback link is invalid')
    return templates.TemplateResponse('feedback_form.html', {
        'request': request,
        'feedback': feedback,
        'entry': feedback.queue_entry,
        'submitted': feedback.submitted_at is not None,
    })


@router.get('/api/feedback/{token}', response_class=JSONResponse)
async def get_feedback_details(token: str, db: Session = Depends(get_db)):
    feedback = db.query(QueueFeedback).filter(QueueFeedback.token == token).first()
    if not feedback:
        raise HTTPException(status_code=404, detail='Feedback link is invalid')

    entry = feedback.queue_entry
    return {
        'success': True,
        'name': entry.name,
        'mobile_number': entry.mobile_number,
        'submitted': feedback.submitted_at is not None,
    }


@router.post('/api/feedback', response_class=JSONResponse)
async def submit_feedback_api(payload: FeedbackSubmission, db: Session = Depends(get_db)):
    feedback = db.query(QueueFeedback).filter(QueueFeedback.token == payload.token).first()
    if not feedback:
        raise HTTPException(status_code=404, detail='Feedback link is invalid')
    if feedback.submitted_at is not None:
        raise HTTPException(status_code=409, detail='Feedback has already been submitted')

    feedback.rating = payload.rating
    feedback.comments = (payload.comments or '').strip()[:2000] or None
    feedback.submitted_at = datetime.utcnow()
    db.commit()
    db.refresh(feedback)

    return {
        'success': True,
        'message': 'Thank you. Your feedback has been submitted successfully.',
        'feedback_id': feedback.id,
        'queue_entry_id': feedback.queue_entry_id,
        'submitted_at': feedback.submitted_at.isoformat(),
    }


@router.get('/admin/feedback', response_class=HTMLResponse)
async def feedback_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth),
    city: Optional[str] = None,
    store_id: Optional[str] = None,
    search: Optional[str] = None,
    feedback_status: str = 'all',
    page: int = 1,
    per_page: int = 25,
):
    selected_store_id = _optional_int(store_id)
    search_clean = (search or '').strip()
    feedback_status = feedback_status if feedback_status in ('all', 'submitted', 'pending') else 'all'
    per_page = per_page if per_page in (10, 25, 50, 100) else 25
    page = max(page, 1)
    stores = db.query(Store).order_by(Store.city.asc(), Store.store_name.asc()).all()

    if current_user.role == UserRole.STORE_ADMIN.value:
        if not current_user.store_id:
            raise HTTPException(status_code=403, detail='Store admin is not linked to a store')
        selected_store_id = current_user.store_id
        assigned_store = db.query(Store).filter(Store.id == current_user.store_id).first()
        city = assigned_store.city if assigned_store else ''
        stores = [assigned_store] if assigned_store else []
    else:
        assigned_store = None

    sync_result = sync_cre_feedback(db)
    sync_message = request.session.pop("cre_sync_message", None)
    sync_error = request.session.pop("cre_sync_error", None)
    if not sync_result.get("success") and not sync_error:
        sync_error = (
            "CRE sync failed; showing cached feedback. "
            + sync_result.get("error", "Unknown error")
        )

    external_query = db.query(ExternalFeedback).filter(
        ExternalFeedback.source_system == "cre",
        ExternalFeedback.submitted_at.isnot(None),
    )
    if search_clean:
        external_term = f"%{search_clean}%"
        external_query = external_query.filter(or_(
            ExternalFeedback.customer_name.ilike(external_term),
            ExternalFeedback.mobile_number.ilike(external_term),
            ExternalFeedback.visit_number.ilike(external_term),
        ))
    if current_user.role == UserRole.STORE_ADMIN.value and assigned_store:
        external_query = external_query.filter(or_(
            ExternalFeedback.external_store_id == current_user.store_id,
            ExternalFeedback.store_name == assigned_store.store_name,
        ))
    elif selected_store_id is not None:
        selected_store = db.query(Store).filter(
            Store.id == selected_store_id
        ).first()
        store_filters = [
            ExternalFeedback.external_store_id == selected_store_id
        ]
        if selected_store:
            store_filters.append(
                ExternalFeedback.store_name == selected_store.store_name
            )
        external_query = external_query.filter(or_(*store_filters))

    cre_feedback_entries = external_query.order_by(
        desc(ExternalFeedback.submitted_at),
        desc(ExternalFeedback.source_updated_at),
    ).limit(250).all()

    query = db.query(QueueEntry).outerjoin(QueueFeedback)
    if city:
        query = query.filter(QueueEntry.city == city)
    if selected_store_id is not None:
        query = query.filter(QueueEntry.store_id == selected_store_id)
    if search_clean:
        term = f"%{search_clean}%"
        query = query.filter(or_(
            QueueEntry.name.ilike(term),
            QueueEntry.mobile_number.ilike(term),
            QueueEntry.token.ilike(term),
        ))
    if feedback_status == 'submitted':
        query = query.filter(QueueFeedback.submitted_at.isnot(None))
    elif feedback_status == 'pending':
        query = query.filter(or_(QueueFeedback.id.is_(None), QueueFeedback.submitted_at.is_(None)))

    total = query.count()
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    entries = (
        query.order_by(desc(QueueFeedback.submitted_at), desc(QueueEntry.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    submitted_count_query = db.query(QueueFeedback).join(QueueEntry).filter(QueueFeedback.submitted_at.isnot(None))
    pending_count_query = db.query(QueueEntry).outerjoin(QueueFeedback).filter(
        or_(QueueFeedback.id.is_(None), QueueFeedback.submitted_at.is_(None))
    )
    if city:
        submitted_count_query = submitted_count_query.filter(QueueEntry.city == city)
        pending_count_query = pending_count_query.filter(QueueEntry.city == city)
    if selected_store_id is not None:
        submitted_count_query = submitted_count_query.filter(QueueEntry.store_id == selected_store_id)
        pending_count_query = pending_count_query.filter(QueueEntry.store_id == selected_store_id)

    grouped = _group([store for store in stores if store])
    query_params = {
        'city': city or '',
        'store_id': selected_store_id or '',
        'search': search_clean,
        'feedback_status': feedback_status,
        'per_page': per_page,
    }

    def page_url(page_number: int) -> str:
        return f"/admin/feedback?{urlencode({**query_params, 'page': page_number})}"

    return templates.TemplateResponse('feedback_dashboard.html', {
        'request': request,
        'user': current_user,
        'user_role': current_user.role,
        'assigned_store': assigned_store,
        'entries': entries,
        'cre_feedback_entries': cre_feedback_entries,
        'cre_feedback_count': len(cre_feedback_entries),
        'cre_sync_result': sync_result,
        'cre_sync_message': sync_message,
        'cre_sync_error': sync_error,
        'stores_by_city': grouped,
        'cities': list(grouped.keys()),
        'selected_city': city or '',
        'selected_store_id': selected_store_id or '',
        'search_query': search_clean,
        'feedback_status': feedback_status,
        'submitted_count': submitted_count_query.count(),
        'pending_count': pending_count_query.count(),
        'page': page,
        'pages': pages,
        'total': total,
        'per_page': per_page,
        'previous_url': page_url(page - 1) if page > 1 else None,
        'next_url': page_url(page + 1) if page < pages else None,
        'is_super_admin': current_user.role == UserRole.SUPER_ADMIN.value,
        'is_store_admin': current_user.role == UserRole.STORE_ADMIN.value,
        'now_utc': datetime.utcnow(),
    })


@router.post('/admin/feedback/sync')
async def sync_feedback_from_cre(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth),
):
    result = sync_cre_feedback(db)
    if result.get("success"):
        request.session["cre_sync_message"] = (
            f"CRE sync completed. {result.get('imported', 0)} record(s) processed."
        )
    else:
        request.session["cre_sync_error"] = (
            "CRE sync failed: " + result.get("error", "Unknown error")
        )
    return RedirectResponse(url="/admin/feedback", status_code=302)


@router.post('/admin/feedback/cre/{feedback_id}/resend')
async def resend_external_feedback(
    request: Request,
    feedback_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth),
):
    feedback = db.query(ExternalFeedback).filter(
        ExternalFeedback.id == feedback_id,
        ExternalFeedback.source_system == "cre",
    ).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="CRE feedback not found")

    if current_user.role == UserRole.STORE_ADMIN.value:
        assigned_store = db.query(Store).filter(
            Store.id == current_user.store_id
        ).first()
        store_matches = (
            feedback.external_store_id == current_user.store_id
            or (
                assigned_store
                and feedback.store_name == assigned_store.store_name
            )
        )
        if not store_matches:
            raise HTTPException(
                status_code=403,
                detail="You can only manage your own store feedback",
            )

    if feedback.submitted_at is not None:
        request.session["cre_sync_error"] = (
            "Feedback is already submitted and cannot be resent."
        )
        return RedirectResponse(url="/admin/feedback", status_code=302)

    try:
        result = resend_cre_feedback(feedback.external_feedback_id)
        feedback.send_status = result.get("status") or "queued"
        feedback.synced_at = datetime.utcnow()
        db.commit()
        request.session["cre_sync_message"] = (
            f"CRE feedback link queued for {feedback.customer_name}."
        )
    except Exception as exc:
        request.session["cre_sync_error"] = f"CRE resend failed: {exc}"

    return RedirectResponse(url="/admin/feedback", status_code=302)


@router.post('/feedback/{token}', response_class=HTMLResponse)
async def submit_feedback(
    request: Request,
    token: str,
    rating: int = Form(...),
    comments: str = Form(''),
    db: Session = Depends(get_db),
):
    feedback = db.query(QueueFeedback).filter(QueueFeedback.token == token).first()
    if not feedback:
        raise HTTPException(status_code=404, detail='Feedback link is invalid')
    if feedback.submitted_at is None:
        if rating < 1 or rating > 5:
            return templates.TemplateResponse('feedback_form.html', {
                'request': request,
                'feedback': feedback,
                'entry': feedback.queue_entry,
                'submitted': False,
                'error': 'Please select a rating from 1 to 5.',
            }, status_code=400)
        feedback.rating = rating
        feedback.comments = comments.strip()[:2000] or None
        feedback.submitted_at = datetime.utcnow()
        db.commit()
        db.refresh(feedback)
    return templates.TemplateResponse('feedback_form.html', {
        'request': request,
        'feedback': feedback,
        'entry': feedback.queue_entry,
        'submitted': True,
    })


@router.post('/admin/queue/send-feedback/{entry_id}')
async def send_feedback_link(
    request: Request,
    entry_id: int,
    city: str = Form(''),
    store_id: str = Form(''),
    tab: str = Form('active'),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth),
):
    entry = db.query(QueueEntry).filter(QueueEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail='Queue entry not found')
    if current_user.role == UserRole.STORE_ADMIN.value and entry.store_id != current_user.store_id:
        raise HTTPException(status_code=403, detail='You can only manage your own store queue')

    feedback, feedback_error = _deliver_feedback(db, request, entry)
    if feedback_error:
        request.session['feedback_error'] = f'Feedback link could not be sent: {feedback_error}'
    else:
        request.session['feedback_message'] = f'Feedback link queued for {entry.name} on WhatsApp.'

    params = {'city': city, 'store_id': store_id, 'tab': 'closed' if tab == 'closed' else 'active'}
    return RedirectResponse(url=f"/admin/queue?{urlencode(params)}", status_code=302)



@router.get('/admin/queue/export')
async def export_queue_excel(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth),
    status: Optional[str] = 'all',
    city: Optional[str] = None,
    store_id: Optional[str] = None,
    search: Optional[str] = None,
):
    selected_store_id = _optional_int(store_id)
    search_clean = (search or '').strip()

    if current_user.role == UserRole.STORE_ADMIN.value:
        if not current_user.store_id:
            raise HTTPException(status_code=403, detail='Store admin is not linked to a store')
        store = db.query(Store).filter(Store.id == current_user.store_id).first()
        city = store.city if store else ""
        selected_store_id = current_user.store_id

    query = db.query(QueueEntry)
    if city:
        query = query.filter(QueueEntry.city == city)
    if selected_store_id is not None:
        query = query.filter(QueueEntry.store_id == selected_store_id)
    if search_clean:
        term = f"%{search_clean}%"
        query = query.filter(
            or_(
                QueueEntry.name.ilike(term),
                QueueEntry.mobile_number.ilike(term),
                QueueEntry.aadhar_number.ilike(term),
                QueueEntry.pan_number.ilike(term),
                QueueEntry.token.ilike(term),
            )
        )
    if current_user.role == UserRole.STORE_ADMIN.value:
        query = query.filter(QueueEntry.store_id == current_user.store_id)

    if status == 'open':
        query = query.filter(QueueEntry.status == 'open')
    elif status == 'closed':
        query = query.filter(QueueEntry.status == 'closed')

    entries = query.order_by(desc(QueueEntry.created_at)).all()

    # Headers for Excel export
    headers = [
        "S.No.",
        "Token",
        "Date & Time (IST)",
        "Visitor Name",
        "Mobile Number",
        "City",
        "Store Name",
        "Address",
        "Email",
        "Aadhaar Number",
        "PAN Number",
        "Status",
    ]

    rows = []
    for idx, entry in enumerate(entries, start=1):
        ist_time = entry.created_at_ist.strftime('%d %b %Y %I:%M %p') if entry.created_at_ist else ''
        store_name = entry.store.store_name if entry.store else ''
        status_label = "Active (Waiting)" if entry.status == 'open' else "Closed (Completed)"
        rows.append([
            idx,
            entry.token or '',
            ist_time,
            entry.name or '',
            entry.mobile_number or '',
            entry.city or '',
            store_name,
            entry.address or '',
            entry.email or '',
            entry.aadhar_number or '',
            entry.pan_number or '',
            status_label,
        ])

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    status_tag = status if status in ['open', 'closed'] else 'all'
    filename_prefix = f"Queue_Entries_{status_tag}_{timestamp}"

    # Generate simple unformatted .xlsx Excel file using openpyxl
    try:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Queue Entries"

        # Header Row (Row 1)
        ws.append(headers)

        # Data Rows (Row 2 onwards)
        for row_data in rows:
            ws.append(row_data)

        stream = io.BytesIO()
        wb.save(stream)
        stream.seek(0)
        return Response(
            content=stream.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename_prefix}.xlsx"'}
        )
    except ImportError:
        # Fallback to UTF-8 BOM CSV if openpyxl is not installed
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)
        csv_bytes = "\ufeff".encode('utf-8') + output.getvalue().encode('utf-8')

        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename_prefix}.csv"'}
        )


@router.post('/admin/queue/close/{entry_id}')
async def close_entry(request: Request, entry_id: int, city: str = Form(''), store_id: str = Form(''), db: Session = Depends(get_db), current_user: AdminUser = Depends(require_admin_auth)):
    entry = db.query(QueueEntry).filter(QueueEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail='Queue entry not found')
    if current_user.role == UserRole.STORE_ADMIN.value and entry.store_id != current_user.store_id:
        raise HTTPException(status_code=403, detail='You can only manage your own store queue')
    entry.status = 'closed'
    db.commit()
    return RedirectResponse(url=f'/admin/queue{_queue_query(city or None, _optional_int(store_id))}', status_code=302)


@router.post('/admin/queue/open/{entry_id}')
async def open_entry(request: Request, entry_id: int, city: str = Form(''), store_id: str = Form(''), db: Session = Depends(get_db), current_user: AdminUser = Depends(require_admin_auth)):
    entry = db.query(QueueEntry).filter(QueueEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail='Queue entry not found')
    if current_user.role == UserRole.STORE_ADMIN.value and entry.store_id != current_user.store_id:
        raise HTTPException(status_code=403, detail='You can only manage your own store queue')
    entry.status = 'open'
    db.commit()
    return RedirectResponse(url=f'/admin/queue{_queue_query(city or None, _optional_int(store_id))}', status_code=302)


@router.post('/admin/queue/admins/create')
async def create_location_admin(request: Request, username: str = Form(...), password: str = Form(...), store_id: int = Form(...), db: Session = Depends(get_db), current_user: AdminUser = Depends(require_admin_auth)):
    if current_user.role != UserRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail='Super admin access required')
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail='Store not found')
    if db.query(AdminUser).filter(AdminUser.username == username.strip()).first():
        raise HTTPException(status_code=400, detail='Username already exists')
    admin = AdminUser(username=username.strip(), password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(), role=UserRole.STORE_ADMIN.value, store_id=store.id)
    db.add(admin)
    db.commit()
    return RedirectResponse(url='/admin/queue', status_code=302)


@router.post('/admin/queue/admins/update-password/{admin_id}')
async def update_store_admin_password(
    request: Request,
    admin_id: int,
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    if current_user.role != UserRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail='Super admin access required')
    admin = db.query(AdminUser).filter(AdminUser.id == admin_id, AdminUser.role == UserRole.STORE_ADMIN.value).first()
    if not admin:
        raise HTTPException(status_code=404, detail='Store admin account not found')
    if not new_password or len(new_password.strip()) < 4:
        raise HTTPException(status_code=400, detail='Password must be at least 4 characters long')
    
    admin.password_hash = bcrypt.hashpw(new_password.strip().encode(), bcrypt.gensalt()).decode()
    db.commit()
    return RedirectResponse(url='/admin/queue', status_code=302)


@router.get('/store/login', response_class=HTMLResponse)
async def store_login_page(request: Request, db: Session = Depends(get_db)):
    if is_authenticated(request):
        user_role = request.session.get("user_role")
        store_id = request.session.get("store_id")
        store_city = request.session.get("store_city")
        if user_role == UserRole.STORE_ADMIN.value and store_id:
            return RedirectResponse(url=f"/admin/queue?city={store_city or ''}&store_id={store_id}", status_code=302)
    return templates.TemplateResponse('store_login.html', {'request': request})


@router.post('/store/login')
async def store_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = authenticate_user(db, username, password)
    if not user or user.role != UserRole.STORE_ADMIN.value:
        return templates.TemplateResponse(
            'store_login.html',
            {
                'request': request,
                'error': 'Invalid store credentials or not a Store Admin account.'
            }
        )
    
    store = db.query(Store).filter(Store.id == user.store_id).first() if user.store_id else None
    if not store:
        return templates.TemplateResponse(
            'store_login.html',
            {
                'request': request,
                'error': 'This store manager account is not assigned to any active store location.'
            }
        )

    # Login user and store session info
    access_token = login_user(request, user)
    request.session["jwt_token"] = access_token
    request.session["user_role"] = user.role
    request.session["store_id"] = store.id
    request.session["store_city"] = store.city
    
    return RedirectResponse(url=f"/admin/queue?city={store.city}&store_id={store.id}", status_code=302)

