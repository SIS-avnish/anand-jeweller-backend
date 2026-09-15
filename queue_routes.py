import csv
import html
import io
import os
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import random
import re
from urllib.parse import urlencode
import bcrypt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, status, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, text
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db, engine
from jwt_auth import require_admin_auth
from auth import authenticate_user, login_user, is_authenticated
from models import AdminUser, QueueEntry, Store, UserRole

router = APIRouter()
templates = Jinja2Templates(directory=['templates', '.'])
CITY_PREFIXES = {'Indore': 'IND', 'Bhopal': 'BHP', 'Raipur': 'RAI'}

# Ensure upload directory for queue documents exists
UPLOAD_DIR = os.path.join("static", "uploads", "queue")
os.makedirs(UPLOAD_DIR, exist_ok=True)
MAX_IMAGE_DIMENSION = 2000


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
    db.commit()
    db.refresh(entry)
    request.session['queue_last_entry_id'] = entry.id
    return RedirectResponse(url='/queue/success', status_code=302)


@router.get('/queue/success', response_class=HTMLResponse)
async def success_page(request: Request, db: Session = Depends(get_db)):
    entry_id = request.session.get('queue_last_entry_id')
    queue_message = request.session.pop('queue_message', None)

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
    })


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

