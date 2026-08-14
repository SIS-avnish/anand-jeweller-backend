from collections import defaultdict
from datetime import datetime, timedelta
import random
import re
from urllib.parse import urlencode
import bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from jwt_auth import require_admin_auth
from auth import authenticate_user, login_user, is_authenticated
from models import AdminUser, QueueEntry, Store, UserRole

router = APIRouter()
templates = Jinja2Templates(directory=['templates', '.'])
CITY_PREFIXES = {'Indore': 'IND', 'Bhopal': 'BHP', 'Raipur': 'RAI'}


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


def _captcha_svg(question: str, seed: int) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="220" height="72" viewBox="0 0 220 72">
  <defs>
    <linearGradient id="g" x1="0%" x2="100%" y1="0%" y2="100%">
      <stop offset="0%" stop-color="#7f1020"/>
      <stop offset="100%" stop-color="#b88714"/>
    </linearGradient>
  </defs>
  <rect width="220" height="72" rx="14" fill="url(#g)"/>
  <circle cx="{42 + seed % 12}" cy="{22 + seed % 8}" r="18" fill="rgba(255,255,255,0.08)"/>
  <circle cx="{150 + seed % 18}" cy="{36 + seed % 10}" r="10" fill="rgba(255,215,0,0.12)"/>
  <text x="50%" y="49%" dominant-baseline="middle" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="28" font-weight="700" fill="#f7d774" letter-spacing="2">{question}</text>
</svg>'''


@router.get('/queue/captcha')
async def queue_captcha(request: Request):
    a, b = random.randint(2, 9), random.randint(1, 9)
    op = random.choice(['+', '-'])
    if op == '-' and b > a:
        a, b = b, a
    ans = a + b if op == '+' else a - b
    q = f'{a} {op} {b} = ?'
    request.session['queue_captcha_answer'] = str(ans)
    return Response(_captcha_svg(q, random.randint(1000, 9999)), media_type='image/svg+xml')


@router.get('/queue/register', response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(get_db), city: Optional[str] = None, store_id: Optional[int] = None):
    stores = db.query(Store).order_by(Store.city.asc(), Store.store_name.asc()).all()
    grouped = _group(stores)
    return templates.TemplateResponse('queue_register.html', {
        'request': request,
        'stores_by_city': grouped,
        'cities': list(grouped.keys()),
        'selected_city': city or next(iter(grouped.keys()), ''),
        'selected_store_id': int(store_id) if store_id else '',
        'captcha_seed': datetime.now().timestamp(),
    })


@router.post('/queue/register')
async def register_visitor(
    request: Request,
    city: str = Form(...),
    store_id: int = Form(...),
    name: str = Form(...),
    address: str = Form(''),
    mobile_number: str = Form(...),
    email: str = Form(''),
    aadhar_number: str = Form(''),
    pan_number: str = Form(''),
    captcha_answer: str = Form(...),
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
            'form_data': {'name': name, 'address': address, 'mobile_number': mobile_number, 'email': email, 'aadhar_number': aadhar_number, 'pan_number': pan_number},
            'captcha_seed': datetime.now().timestamp(),
        })

    print(f"[DEBUG] Session Captcha: {request.session.get('queue_captcha_answer')} | Submitted: {captcha_answer.strip()}")
    if request.session.get('queue_captcha_answer') != captcha_answer.strip():
        return error('Captcha did not match. Please try again.')
    if not store or store.city != city:
        return error('Please choose a valid store for the selected city.')

    mobile = _mobile(mobile_number)
    if len(mobile) < 10 or len(mobile) > 15:
        return error('Please enter a valid mobile number.')
    if len(name.strip()) < 2:
        return error('Please enter the visitor name.')

    entry = QueueEntry(
        store_id=store.id,
        city=city,
        name=name.strip(),
        address=address.strip() or None,
        mobile_number=mobile,
        email=email.strip() or None,
        aadhar_number=aadhar_number.strip() or None,
        pan_number=pan_number.strip() or None,
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
    })


@router.get('/admin/queue', response_class=HTMLResponse)
async def queue_dashboard(request: Request, db: Session = Depends(get_db), current_user: AdminUser = Depends(require_admin_auth), city: Optional[str] = None, store_id: Optional[str] = None):
    stores = db.query(Store).order_by(Store.city.asc(), Store.store_name.asc()).all()
    selected_store_id = _optional_int(store_id)
    if current_user.role == UserRole.STORE_ADMIN.value:
        if not current_user.store_id:
            raise HTTPException(status_code=403, detail='Store admin is not linked to a store')
        store = db.query(Store).filter(Store.id == current_user.store_id).first()
        expected_city = store.city if store else ""
        expected_store_id = current_user.store_id
        if request.query_params.get('city') != expected_city or request.query_params.get('store_id') != str(expected_store_id):
            return RedirectResponse(url=f"/admin/queue?city={expected_city}&store_id={expected_store_id}", status_code=302)
        city = expected_city
        selected_store_id = expected_store_id
        stores = [store] if store else []
    grouped = _group([s for s in stores if s])
    base_query = db.query(QueueEntry)
    if city:
        base_query = base_query.filter(QueueEntry.city == city)
    if selected_store_id is not None:
        base_query = base_query.filter(QueueEntry.store_id == selected_store_id)
    if current_user.role == UserRole.STORE_ADMIN.value:
        base_query = base_query.filter(QueueEntry.store_id == current_user.store_id)

    active_entries = base_query.filter(QueueEntry.status == 'open').order_by(desc(QueueEntry.created_at)).all()
    closed_entries = base_query.filter(QueueEntry.status == 'closed').order_by(desc(QueueEntry.created_at)).all()

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
        'active_entries': active_entries,
        'closed_entries': closed_entries,
        'today_total_visitors': today_total_visitors,
        'today_active_count': today_active_count,
        'today_completed_count': today_completed_count,
        'all_time_total_count': all_time_total_count,
        'admins': admins,
        'is_super_admin': current_user.role == UserRole.SUPER_ADMIN.value,
        'is_store_admin': current_user.role == UserRole.STORE_ADMIN.value,
    })


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

