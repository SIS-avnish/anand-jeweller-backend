from fastapi import APIRouter, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime
from typing import Optional
import os
import uuid
from pathlib import Path

from database import get_db
from models import AdminUser, GoldRate, Store, ContactEnquiry, Guide, About, Team, Mission, Terms, Vision, Award, Achievement, Notification, UserRole, CustomerUser
from auth import authenticate_user, login_user, logout_user, get_current_user, is_authenticated, require_super_admin, require_contact_access, is_super_admin
from jwt_auth import require_admin_auth

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Template response utility function
def render_template(template_name: str, context: dict, current_user: AdminUser = None):
    """Utility function to render templates with consistent context"""
    if current_user:
        context.update({
            "user": current_user,
            "user_role": current_user.role
        })
    return templates.TemplateResponse(template_name, context)

# File upload utility function
async def save_uploaded_file(file: Optional[UploadFile], folder: str) -> Optional[str]:
    """Save uploaded file and return the file path, or None if no file uploaded"""
    if not file or not file.filename:
        return None
    
    # Create uploads directory if it doesn't exist
    upload_dir = Path("static/uploads") / folder
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate unique filename
    file_extension = Path(file.filename).suffix
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = upload_dir / unique_filename
    
    # Save the file
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Return the relative path for database storage
    return f"/static/uploads/{folder}/{unique_filename}"

# Login page
@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/admin", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})

# Login form handler
@router.post("/admin/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = authenticate_user(db, username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html", 
            {
                "request": request, 
                "error": "Invalid username or password"
            }
        )
    
    # Login user and get JWT token
    access_token = login_user(request, user)
    
    # Store token in session for JavaScript access
    request.session["jwt_token"] = access_token
    
    return RedirectResponse(url="/admin", status_code=302)

# Logout
@router.get("/admin/logout")
async def logout(request: Request):
    logout_user(request)
    return RedirectResponse(url="/admin/login", status_code=302)

# Dashboard home
@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    print(f"Dashboard: User {current_user.username} with role {current_user.role}")  # Debug logging
    
    # Check user role and show appropriate dashboard
    if current_user.role == UserRole.CONTACT_MANAGER.value:
        # Contact Manager sees only contact enquiries dashboard
        total_enquiries = db.query(ContactEnquiry).count()
        recent_enquiries = db.query(ContactEnquiry).order_by(desc(ContactEnquiry.created_at)).limit(10).all()
        
        jwt_token = request.session.get("jwt_token", "")
        
        print(f"Contact Manager Dashboard - Enquiries: {total_enquiries}")  # Debug logging
        
        return templates.TemplateResponse("contact_manager_dashboard.html", {
            "request": request,
            "user": current_user,
            "user_role": current_user.role,
            "total_enquiries": total_enquiries,
            "recent_enquiries": recent_enquiries,
            "jwt_token": jwt_token
        })
    
    # Super Admin sees full dashboard
    total_rates = db.query(GoldRate).count()
    total_stores = db.query(Store).count()
    total_enquiries = db.query(ContactEnquiry).count()
    total_guides = db.query(Guide).count()
    total_about = db.query(About).count()
    total_team = db.query(Team).count()
    total_missions = db.query(Mission).count()
    total_terms = db.query(Terms).count()
    total_awards = db.query(Award).count()
    total_achievements = db.query(Achievement).count()
    total_notifications = db.query(Notification).count()
    latest_rate = db.query(GoldRate).order_by(desc(GoldRate.release_datetime)).first()
    total_registered_users = db.query(CustomerUser).filter(
    CustomerUser.is_deleted == 0
    ).count()
    
    # Get JWT token from session for frontend use
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": current_user,
        "user_role": current_user.role,
        "total_rates": total_rates,
        "total_stores": total_stores,
        "total_enquiries": total_enquiries,
        "total_guides": total_guides,
        "total_about": total_about,
        "total_team": total_team,
        "total_missions": total_missions,
        "total_terms": total_terms,
        "total_awards": total_awards,
        "total_achievements": total_achievements,
        "total_notifications": total_notifications,
        "total_registered_users": total_registered_users,
        "latest_rate": latest_rate,
        "jwt_token": jwt_token
    })

# List all gold rates - Super Admin only
@router.get("/admin/gold-rates", response_class=HTMLResponse)
async def list_gold_rates(
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = require_super_admin(request, db)
    gold_rates = db.query(GoldRate).order_by(desc(GoldRate.release_datetime)).all()
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("gold_rates/list.html", {
        "request": request,
        "user": current_user,
        "user_role": current_user.role,
        "gold_rates": gold_rates,
        "jwt_token": jwt_token
    })

# Add gold rate form
@router.get("/admin/gold-rates/add", response_class=HTMLResponse)
async def add_gold_rate_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "gold_rates/add.html",
        {
            "request": request,
            "user": current_user,
            "jwt_token": jwt_token
        }
    )

# Add gold rate handler
@router.post("/admin/gold-rates/add")
async def add_gold_rate(
    request: Request,
    # 24K Gold rates
    gold_24k_new_rate: float = Form(...),
    gold_24k_exchange_rate: float = Form(...),
    gold_24k_making_charges: float = Form(...),
    # 22K Gold rates
    gold_22k_new_rate: float = Form(...),
    gold_22k_exchange_rate: float = Form(...),
    gold_22k_making_charges: float = Form(...),
    # 18K Gold rates
    gold_18k_new_rate: float = Form(...),
    gold_18k_exchange_rate: float = Form(...),
    gold_18k_making_charges: float = Form(...),
    # Common fields
    release_datetime: str = Form(...),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Parse datetime
        release_dt = datetime.fromisoformat(release_datetime.replace('T', ' '))
        
        # Check for duplicates (by release datetime)
        existing = db.query(GoldRate).filter(
            GoldRate.release_datetime == release_dt
        ).first()
        
        if existing:
            current_user = get_current_user(request, db)
            return templates.TemplateResponse(
                "gold_rates/add.html",
                {
                    "request": request,
                    "user": current_user,
                    "error": f"A gold rate already exists for this date and time",
                    "jwt_token": request.session.get("jwt_token", "")
                }
            )
        
        # Create new consolidated gold rate
        gold_rate = GoldRate(
            gold_24k_new_rate=gold_24k_new_rate,
            gold_24k_exchange_rate=gold_24k_exchange_rate,
            gold_24k_making_charges=gold_24k_making_charges,
            gold_22k_new_rate=gold_22k_new_rate,
            gold_22k_exchange_rate=gold_22k_exchange_rate,
            gold_22k_making_charges=gold_22k_making_charges,
            gold_18k_new_rate=gold_18k_new_rate,
            gold_18k_exchange_rate=gold_18k_exchange_rate,
            gold_18k_making_charges=gold_18k_making_charges,
            release_datetime=release_dt
        )
        
        db.add(gold_rate)
        db.commit()
        
        return RedirectResponse(url="/admin/gold-rates", status_code=302)
        
    except Exception as e:
        current_user = get_current_user(request, db)
        return templates.TemplateResponse(
            "gold_rates/add.html",
            {
                "request": request,
                "user": current_user,
                "error": f"Error adding gold rate: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Edit gold rate form
@router.get("/admin/gold-rates/edit/{rate_id}", response_class=HTMLResponse)
async def edit_gold_rate_form(
    request: Request,
    rate_id: int,
    db: Session = Depends(get_db)
):
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    gold_rate = db.query(GoldRate).filter(GoldRate.id == rate_id).first()
    if not gold_rate:
        raise HTTPException(status_code=404, detail="Gold rate not found")
    
    current_user = get_current_user(request, db)
    
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "gold_rates/edit.html",
        {
            "request": request,
            "user": current_user,
            "gold_rate": gold_rate,
            "jwt_token": jwt_token
        }
    )

# Edit gold rate handler
@router.post("/admin/gold-rates/edit/{rate_id}")
async def edit_gold_rate(
    request: Request,
    rate_id: int,
    # 24K Gold rates
    gold_24k_new_rate: float = Form(...),
    gold_24k_exchange_rate: float = Form(...),
    gold_24k_making_charges: float = Form(...),
    # 22K Gold rates
    gold_22k_new_rate: float = Form(...),
    gold_22k_exchange_rate: float = Form(...),
    gold_22k_making_charges: float = Form(...),
    # 18K Gold rates
    gold_18k_new_rate: float = Form(...),
    gold_18k_exchange_rate: float = Form(...),
    gold_18k_making_charges: float = Form(...),
    # Common fields
    release_datetime: str = Form(...),
    db: Session = Depends(get_db)
):
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        gold_rate = db.query(GoldRate).filter(GoldRate.id == rate_id).first()
        if not gold_rate:
            raise HTTPException(status_code=404, detail="Gold rate not found")
        
        # Parse datetime
        release_dt = datetime.fromisoformat(release_datetime.replace('T', ' '))
        
        # Check for duplicates (excluding current record)
        existing = db.query(GoldRate).filter(
            GoldRate.release_datetime == release_dt,
            GoldRate.id != rate_id
        ).first()
        
        if existing:
            current_user = get_current_user(request, db)
            return templates.TemplateResponse(
                "gold_rates/edit.html",
                {
                    "request": request,
                    "user": current_user,
                    "gold_rate": gold_rate,
                    "error": f"A gold rate already exists for this date and time",
                    "jwt_token": request.session.get("jwt_token", "")
                }
            )
        
        # Update consolidated gold rate
        gold_rate.gold_24k_new_rate = gold_24k_new_rate
        gold_rate.gold_24k_exchange_rate = gold_24k_exchange_rate
        gold_rate.gold_24k_making_charges = gold_24k_making_charges
        gold_rate.gold_22k_new_rate = gold_22k_new_rate
        gold_rate.gold_22k_exchange_rate = gold_22k_exchange_rate
        gold_rate.gold_22k_making_charges = gold_22k_making_charges
        gold_rate.gold_18k_new_rate = gold_18k_new_rate
        gold_rate.gold_18k_exchange_rate = gold_18k_exchange_rate
        gold_rate.gold_18k_making_charges = gold_18k_making_charges
        gold_rate.release_datetime = release_dt
        
        db.commit()
        
        return RedirectResponse(url="/admin/gold-rates", status_code=302)
        
    except Exception as e:
        current_user = get_current_user(request, db)
        gold_rate = db.query(GoldRate).filter(GoldRate.id == rate_id).first()
        return templates.TemplateResponse(
            "gold_rates/edit.html",
            {
                "request": request,
                "user": current_user,
                "gold_rate": gold_rate,
                "error": f"Error updating gold rate: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Delete gold rate
@router.get("/admin/gold-rates/delete/{rate_id}")
async def delete_gold_rate(
    request: Request,
    rate_id: int,
    db: Session = Depends(get_db)
):
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    gold_rate = db.query(GoldRate).filter(GoldRate.id == rate_id).first()
    if not gold_rate:
        raise HTTPException(status_code=404, detail="Gold rate not found")
    
    db.delete(gold_rate)
    db.commit()
    
    return RedirectResponse(url="/admin/gold-rates", status_code=302)

# ABOUT SECTION ROUTES

# List all about entries
@router.get("/admin/about", response_class=HTMLResponse)
async def list_about(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    about_entries = db.query(About).order_by(desc(About.created_at)).all()
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "about/list.html",
        {
            "request": request,
            "user": current_user,
            "about_entries": about_entries,
            "jwt_token": jwt_token
        }
    )

# Add about entry form
@router.get("/admin/about/add", response_class=HTMLResponse)
async def add_about_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "about/add.html",
        {
            "request": request,
            "user": current_user,
            "jwt_token": jwt_token
        }
    )

# Add about entry handler
@router.post("/admin/about/add")
async def add_about(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    try:
        # Handle file upload
        image_path = await save_uploaded_file(image, "about")
        
        about_entry = About(
            title=title,
            content=content,
            image=image_path
        )
        
        db.add(about_entry)
        db.commit()
        
        return RedirectResponse(url="/admin/about", status_code=302)
        
    except Exception as e:
        return templates.TemplateResponse(
            "about/add.html",
            {
                "request": request,
                "user": current_user,
                "error": f"Error adding about entry: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Edit about entry form
@router.get("/admin/about/edit/{about_id}", response_class=HTMLResponse)
async def edit_about_form(
    request: Request,
    about_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    about_entry = db.query(About).filter(About.id == about_id).first()
    if not about_entry:
        raise HTTPException(status_code=404, detail="About entry not found")
    
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "about/edit.html",
        {
            "request": request,
            "user": current_user,
            "about_entry": about_entry,
            "jwt_token": jwt_token
        }
    )

# Edit about entry handler
@router.post("/admin/about/edit/{about_id}")
async def edit_about(
    request: Request,
    about_id: int,
    title: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    try:
        about_entry = db.query(About).filter(About.id == about_id).first()
        if not about_entry:
            raise HTTPException(status_code=404, detail="About entry not found")
        
        # Handle file upload - only update image if new file is uploaded
        image_path = await save_uploaded_file(image, "about")
        
        about_entry.title = title
        about_entry.content = content
        if image_path:  # Only update image if new file was uploaded
            about_entry.image = image_path
        
        db.commit()
        
        return RedirectResponse(url="/admin/about", status_code=302)
        
    except Exception as e:
        about_entry = db.query(About).filter(About.id == about_id).first()
        return templates.TemplateResponse(
            "about/edit.html",
            {
                "request": request,
                "user": current_user,
                "about_entry": about_entry,
                "error": f"Error updating about entry: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Delete about entry
@router.get("/admin/about/delete/{about_id}")
async def delete_about(
    request: Request,
    about_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    about_entry = db.query(About).filter(About.id == about_id).first()
    if not about_entry:
        raise HTTPException(status_code=404, detail="About entry not found")
    
    db.delete(about_entry)
    db.commit()
    
    return RedirectResponse(url="/admin/about", status_code=302)

# TEAM SECTION ROUTES

# List all team members
@router.get("/admin/team", response_class=HTMLResponse)
async def list_team(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    team_members = db.query(Team).order_by(desc(Team.created_at)).all()
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "team/list.html",
        {
            "request": request,
            "user": current_user,
            "team_members": team_members,
            "jwt_token": jwt_token
        }
    )

# Add team member form
@router.get("/admin/team/add", response_class=HTMLResponse)
async def add_team_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "team/add.html",
        {
            "request": request,
            "user": current_user,
            "jwt_token": jwt_token
        }
    )

# Add team member handler
@router.post("/admin/team/add")
async def add_team(
    request: Request,
    position: str = Form(...),
    name: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    try:
        # Handle file upload
        image_path = await save_uploaded_file(image, "team")
        
        team_member = Team(
            position=position,
            name=name,
            content=content,
            image=image_path
        )
        
        db.add(team_member)
        db.commit()
        
        return RedirectResponse(url="/admin/team", status_code=302)
        
    except Exception as e:
        return templates.TemplateResponse(
            "team/add.html",
            {
                "request": request,
                "user": current_user,
                "error": f"Error adding team member: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Edit team member form
@router.get("/admin/team/edit/{team_id}", response_class=HTMLResponse)
async def edit_team_form(
    request: Request,
    team_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    team_member = db.query(Team).filter(Team.id == team_id).first()
    if not team_member:
        raise HTTPException(status_code=404, detail="Team member not found")
    
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "team/edit.html",
        {
            "request": request,
            "user": current_user,
            "team_member": team_member,
            "jwt_token": jwt_token
        }
    )

# Edit team member handler
@router.post("/admin/team/edit/{team_id}")
async def edit_team(
    request: Request,
    team_id: int,
    position: str = Form(...),
    name: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    try:
        team_member = db.query(Team).filter(Team.id == team_id).first()
        if not team_member:
            raise HTTPException(status_code=404, detail="Team member not found")
        
        # Handle file upload - only update image if new file is uploaded
        image_path = await save_uploaded_file(image, "team")
        
        team_member.position = position
        team_member.name = name
        team_member.content = content
        if image_path:  # Only update image if new file was uploaded
            team_member.image = image_path
        
        db.commit()
        
        return RedirectResponse(url="/admin/team", status_code=302)
        
    except Exception as e:
        team_member = db.query(Team).filter(Team.id == team_id).first()
        return templates.TemplateResponse(
            "team/edit.html",
            {
                "request": request,
                "user": current_user,
                "team_member": team_member,
                "error": f"Error updating team member: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Delete team member
@router.get("/admin/team/delete/{team_id}")
async def delete_team(
    request: Request,
    team_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    team_member = db.query(Team).filter(Team.id == team_id).first()
    if not team_member:
        raise HTTPException(status_code=404, detail="Team member not found")
    
    db.delete(team_member)
    db.commit()
    
    return RedirectResponse(url="/admin/team", status_code=302)

# MISSION SECTION ROUTES

# List all missions
@router.get("/admin/missions", response_class=HTMLResponse)
async def list_missions(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    missions = db.query(Mission).order_by(desc(Mission.created_at)).all()
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "missions/list.html",
        {
            "request": request,
            "user": current_user,
            "missions": missions,
            "jwt_token": jwt_token
        }
    )

# Add mission form
@router.get("/admin/missions/add", response_class=HTMLResponse)
async def add_mission_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "missions/add.html",
        {
            "request": request,
            "user": current_user,
            "jwt_token": jwt_token
        }
    )

# Add mission handler
@router.post("/admin/missions/add")
async def add_mission(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    try:
        # Handle file upload
        image_path = await save_uploaded_file(image, "missions")
        
        mission = Mission(
            title=title,
            content=content,
            image=image_path
        )
        
        db.add(mission)
        db.commit()
        
        return RedirectResponse(url="/admin/missions", status_code=302)
        
    except Exception as e:
        return templates.TemplateResponse(
            "missions/add.html",
            {
                "request": request,
                "user": current_user,
                "error": f"Error adding mission: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Edit mission form
@router.get("/admin/missions/edit/{mission_id}", response_class=HTMLResponse)
async def edit_mission_form(
    request: Request,
    mission_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "missions/edit.html",
        {
            "request": request,
            "user": current_user,
            "mission": mission,
            "jwt_token": jwt_token
        }
    )

# Edit mission handler
@router.post("/admin/missions/edit/{mission_id}")
async def edit_mission(
    request: Request,
    mission_id: int,
    title: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    try:
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if not mission:
            raise HTTPException(status_code=404, detail="Mission not found")
        
        # Handle file upload - only update image if new file is uploaded
        image_path = await save_uploaded_file(image, "missions")
        
        mission.title = title
        mission.content = content
        if image_path:  # Only update image if new file was uploaded
            mission.image = image_path
        
        db.commit()
        
        return RedirectResponse(url="/admin/missions", status_code=302)
        
    except Exception as e:
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        return templates.TemplateResponse(
            "missions/edit.html",
            {
                "request": request,
                "user": current_user,
                "mission": mission,
                "error": f"Error updating mission: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Delete mission
@router.get("/admin/missions/delete/{mission_id}")
async def delete_mission(
    request: Request,
    mission_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    db.delete(mission)
    db.commit()
    
    return RedirectResponse(url="/admin/missions", status_code=302)

# TERMS SECTION ROUTES

# List all terms
@router.get("/admin/terms", response_class=HTMLResponse)
async def list_terms(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    terms = db.query(Terms).order_by(desc(Terms.created_at)).all()
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "terms/list.html",
        {
            "request": request,
            "user": current_user,
            "user_role": current_user.role,
            "terms": terms,
            "jwt_token": jwt_token
        }
    )

# Add terms form
@router.get("/admin/terms/add", response_class=HTMLResponse)
async def add_terms_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "terms/add.html",
        {
            "request": request,
            "user": current_user,
            "user_role": current_user.role,
            "jwt_token": jwt_token
        }
    )

# Add terms handler
@router.post("/admin/terms/add")
async def add_terms(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    try:
        # Handle file upload
        image_path = await save_uploaded_file(image, "terms")
        
        terms = Terms(
            title=title,
            content=content,
            image=image_path
        )
        
        db.add(terms)
        db.commit()
        
        return RedirectResponse(url="/admin/terms", status_code=302)
        
    except Exception as e:
        return templates.TemplateResponse(
            "terms/add.html",
            {
                "request": request,
                "user": current_user,
                "error": f"Error adding terms: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Edit terms form
@router.get("/admin/terms/edit/{terms_id}", response_class=HTMLResponse)
async def edit_terms_form(
    request: Request,
    terms_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    terms = db.query(Terms).filter(Terms.id == terms_id).first()
    if not terms:
        raise HTTPException(status_code=404, detail="Terms not found")
    
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "terms/edit.html",
        {
            "request": request,
            "user": current_user,
            "user_role": current_user.role,
            "terms": terms,
            "jwt_token": jwt_token
        }
    )

# Edit terms handler
@router.post("/admin/terms/edit/{terms_id}")
async def edit_terms(
    request: Request,
    terms_id: int,
    title: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    try:
        terms = db.query(Terms).filter(Terms.id == terms_id).first()
        if not terms:
            raise HTTPException(status_code=404, detail="Terms not found")
        
        # Handle file upload - only update image if new file is uploaded
        image_path = await save_uploaded_file(image, "terms")
        
        terms.title = title
        terms.content = content
        if image_path:  # Only update image if new file was uploaded
            terms.image = image_path
        
        db.commit()
        
        return RedirectResponse(url="/admin/terms", status_code=302)
        
    except Exception as e:
        terms = db.query(Terms).filter(Terms.id == terms_id).first()
        return templates.TemplateResponse(
            "terms/edit.html",
            {
                "request": request,
                "user": current_user,
                "terms": terms,
                "error": f"Error updating terms: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Delete terms
@router.get("/admin/terms/delete/{terms_id}")
async def delete_terms(
    request: Request,
    terms_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    terms = db.query(Terms).filter(Terms.id == terms_id).first()
    if not terms:
        raise HTTPException(status_code=404, detail="Terms not found")
    
    db.delete(terms)
    db.commit()
    
    return RedirectResponse(url="/admin/terms", status_code=302)

# Vision Management Routes

# List vision entries
@router.get("/admin/visions", response_class=HTMLResponse)
async def list_visions(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    jwt_token = request.session.get("jwt_token", "")
    
    vision_entries = db.query(Vision).order_by(desc(Vision.created_at)).all()
    
    return templates.TemplateResponse(
        "visions/list.html",
        {
            "request": request,
            "user": current_user,
            "vision_entries": vision_entries,
            "jwt_token": jwt_token
        }
    )

# Add vision entry form
@router.get("/admin/visions/add", response_class=HTMLResponse)
async def add_vision_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "visions/add.html",
        {
            "request": request,
            "user": current_user,
            "jwt_token": jwt_token
        }
    )

# Add vision entry handler
@router.post("/admin/visions/add")
async def add_vision(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    try:
        # Handle file upload
        image_path = await save_uploaded_file(image, "visions")
        
        vision_entry = Vision(
            title=title,
            content=content,
            image=image_path
        )
        
        db.add(vision_entry)
        db.commit()
        
        return RedirectResponse(url="/admin/visions", status_code=302)
        
    except Exception as e:
        return templates.TemplateResponse(
            "visions/add.html",
            {
                "request": request,
                "user": current_user,
                "error": f"Error adding vision entry: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Edit vision entry form
@router.get("/admin/visions/edit/{vision_id}", response_class=HTMLResponse)
async def edit_vision_form(
    request: Request,
    vision_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    vision_entry = db.query(Vision).filter(Vision.id == vision_id).first()
    if not vision_entry:
        raise HTTPException(status_code=404, detail="Vision entry not found")
    
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse(
        "visions/edit.html",
        {
            "request": request,
            "user": current_user,
            "vision_entry": vision_entry,
            "jwt_token": jwt_token
        }
    )

# Edit vision entry handler
@router.post("/admin/visions/edit/{vision_id}")
async def edit_vision(
    request: Request,
    vision_id: int,
    title: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    try:
        vision_entry = db.query(Vision).filter(Vision.id == vision_id).first()
        if not vision_entry:
            raise HTTPException(status_code=404, detail="Vision entry not found")
        
        # Handle file upload - only update image if new file is uploaded
        image_path = await save_uploaded_file(image, "visions")
        
        vision_entry.title = title
        vision_entry.content = content
        if image_path:  # Only update image if new file was uploaded
            vision_entry.image = image_path
        
        db.commit()
        
        return RedirectResponse(url="/admin/visions", status_code=302)
        
    except Exception as e:
        vision_entry = db.query(Vision).filter(Vision.id == vision_id).first()
        return templates.TemplateResponse(
            "visions/edit.html",
            {
                "request": request,
                "user": current_user,
                "vision_entry": vision_entry,
                "error": f"Error updating vision entry: {str(e)}",
                "jwt_token": request.session.get("jwt_token", "")
            }
        )

# Delete vision entry
@router.get("/admin/visions/delete/{vision_id}")
async def delete_vision(
    request: Request,
    vision_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    vision_entry = db.query(Vision).filter(Vision.id == vision_id).first()
    if not vision_entry:
        raise HTTPException(status_code=404, detail="Vision entry not found")
    
    db.delete(vision_entry)
    db.commit()
    
    return RedirectResponse(url="/admin/visions", status_code=302)

# ======================
# Award Management
# ======================

@router.get("/admin/awards", response_class=HTMLResponse)
async def list_awards(
    request: Request, 
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """List all awards"""
    awards = db.query(Award).order_by(desc(Award.created_at)).all()
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("awards/list.html", {
        "request": request,
        "user": current_user,
        "awards": awards,
        "page_title": "Awards Management",
        "jwt_token": jwt_token
    })

@router.get("/admin/awards/add", response_class=HTMLResponse)
async def add_award_form(
    request: Request,
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Show add award form"""
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("awards/add.html", {
        "request": request,
        "user": current_user,
        "page_title": "Add New Award",
        "jwt_token": jwt_token
    })

@router.post("/admin/awards/add")
async def add_award(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Add new award"""
    
    try:
        new_award = Award(
            title=title,
            content=content
        )
        
        db.add(new_award)
        db.commit()
        
        return RedirectResponse(url="/admin/awards", status_code=302)
        
    except Exception as e:
        jwt_token = request.session.get("jwt_token", "")
        return templates.TemplateResponse("awards/add.html", {
            "request": request,
            "user": current_user,
            "error": f"Failed to add award: {str(e)}",
            "title": title,
            "content": content,
            "page_title": "Add New Award",
            "jwt_token": jwt_token
        })

@router.get("/admin/awards/edit/{award_id}", response_class=HTMLResponse)
async def edit_award_form(
    request: Request, 
    award_id: int, 
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Show edit award form"""
    award = db.query(Award).filter(Award.id == award_id).first()
    
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("awards/edit.html", {
        "request": request,
        "user": current_user,
        "award": award,
        "page_title": f"Edit Award - {award.title}",
        "jwt_token": jwt_token
    })

@router.post("/admin/awards/edit/{award_id}")
async def edit_award(
    request: Request,
    award_id: int,
    title: str = Form(...),
    content: str = Form(...),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Update award"""
    award = db.query(Award).filter(Award.id == award_id).first()
    
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    
    try:
        award.title = title
        award.content = content
        
        db.commit()
        
        return RedirectResponse(url="/admin/awards", status_code=302)
        
    except Exception as e:
        jwt_token = request.session.get("jwt_token", "")
        return templates.TemplateResponse("awards/edit.html", {
            "request": request,
            "user": current_user,
            "award": award,
            "error": f"Failed to update award: {str(e)}",
            "page_title": f"Edit Award - {award.title}",
            "jwt_token": jwt_token
        })

@router.post("/admin/awards/delete/{award_id}")
async def delete_award(
    request: Request, 
    award_id: int, 
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Delete award"""
    award = db.query(Award).filter(Award.id == award_id).first()
    
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    
    db.delete(award)
    db.commit()
    
    return RedirectResponse(url="/admin/awards", status_code=302)

# ======================
# Achievement Management
# ======================

@router.get("/admin/achievements", response_class=HTMLResponse)
async def list_achievements(
    request: Request, 
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """List all achievements"""
    achievements = db.query(Achievement).order_by(desc(Achievement.date)).all()
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("achievements/list.html", {
        "request": request,
        "user": current_user,
        "achievements": achievements,
        "page_title": "Achievements Management",
        "jwt_token": jwt_token
    })

@router.get("/admin/achievements/add", response_class=HTMLResponse)
async def add_achievement_form(
    request: Request,
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Show add achievement form"""
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("achievements/add.html", {
        "request": request,
        "user": current_user,
        "page_title": "Add New Achievement",
        "jwt_token": jwt_token
    })

@router.post("/admin/achievements/add")
async def add_achievement(
    request: Request,
    title: str = Form(...),
    date: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Add new achievement"""
    
    image_path = None
    
    try:
        # Handle image upload
        if image and image.filename:
            # Create unique filename
            file_extension = Path(image.filename).suffix
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            
            # Save file
            upload_dir = Path("static/uploads/achievements")
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = upload_dir / unique_filename
            
            with open(file_path, "wb") as buffer:
                content_bytes = await image.read()
                buffer.write(content_bytes)
            
            image_path = f"/static/uploads/achievements/{unique_filename}"
        
        # Parse date
        achievement_date = datetime.strptime(date, "%Y-%m-%d")
        
        new_achievement = Achievement(
            title=title,
            date=achievement_date,
            content=content,
            image=image_path
        )
        
        db.add(new_achievement)
        db.commit()
        
        return RedirectResponse(url="/admin/achievements", status_code=302)
        
    except Exception as e:
        jwt_token = request.session.get("jwt_token", "")
        return templates.TemplateResponse("achievements/add.html", {
            "request": request,
            "user": current_user,
            "error": f"Failed to add achievement: {str(e)}",
            "title": title,
            "date": date,
            "content": content,
            "page_title": "Add New Achievement",
            "jwt_token": jwt_token
        })

@router.get("/admin/achievements/edit/{achievement_id}", response_class=HTMLResponse)
async def edit_achievement_form(
    request: Request, 
    achievement_id: int, 
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Show edit achievement form"""
    achievement = db.query(Achievement).filter(Achievement.id == achievement_id).first()
    
    if not achievement:
        raise HTTPException(status_code=404, detail="Achievement not found")
    
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("achievements/edit.html", {
        "request": request,
        "user": current_user,
        "achievement": achievement,
        "page_title": f"Edit Achievement - {achievement.title}",
        "jwt_token": jwt_token
    })

@router.post("/admin/achievements/edit/{achievement_id}")
async def edit_achievement(
    request: Request,
    achievement_id: int,
    title: str = Form(...),
    date: str = Form(...),
    content: str = Form(...),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Update achievement"""
    
    achievement = db.query(Achievement).filter(Achievement.id == achievement_id).first()
    
    if not achievement:
        raise HTTPException(status_code=404, detail="Achievement not found")
    
    try:
        # Handle image upload
        if image and image.filename:
            # Create unique filename
            file_extension = Path(image.filename).suffix
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            
            # Save file
            upload_dir = Path("static/uploads/achievements")
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = upload_dir / unique_filename
            
            with open(file_path, "wb") as buffer:
                content_bytes = await image.read()
                buffer.write(content_bytes)
            
            achievement.image = f"/static/uploads/achievements/{unique_filename}"
        
        # Parse date
        achievement_date = datetime.strptime(date, "%Y-%m-%d")
        
        achievement.title = title
        achievement.date = achievement_date
        achievement.content = content
        
        db.commit()
        
        return RedirectResponse(url="/admin/achievements", status_code=302)
        
    except Exception as e:
        jwt_token = request.session.get("jwt_token", "")
        return templates.TemplateResponse("achievements/edit.html", {
            "request": request,
            "user": current_user,
            "achievement": achievement,
            "error": f"Failed to update achievement: {str(e)}",
            "page_title": f"Edit Achievement - {achievement.title}",
            "jwt_token": jwt_token
        })

@router.post("/admin/achievements/delete/{achievement_id}")
async def delete_achievement(
    request: Request, 
    achievement_id: int, 
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Delete achievement"""
    achievement = db.query(Achievement).filter(Achievement.id == achievement_id).first()
    
    if not achievement:
        raise HTTPException(status_code=404, detail="Achievement not found")
    
    db.delete(achievement)
    db.commit()
    
    return RedirectResponse(url="/admin/achievements", status_code=302)

# ========================
# Notification Management
# =======================

@router.get("/admin/notifications", response_class=HTMLResponse)
async def list_notifications(
    request: Request, 
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """List all notifications"""
    notifications = db.query(Notification).order_by(desc(Notification.datetime)).all()
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("notifications/list.html", {
        "request": request,
        "user": current_user,
        "user_role": current_user.role,
        "notifications": notifications,
        "page_title": "Notifications Management",
        "jwt_token": jwt_token
    })

@router.get("/admin/notifications/add", response_class=HTMLResponse)
async def add_notification_form(
    request: Request,
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Show add notification form"""
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("notifications/add.html", {
        "request": request,
        "user": current_user,
        "user_role": current_user.role,
        "page_title": "Add New Notification",
        "jwt_token": jwt_token
    })

@router.post("/admin/notifications/add")
async def add_notification(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    datetime_str: str = Form(...),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Add new notification"""
    
    try:
        # Parse datetime
        notification_datetime = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M")
        
        new_notification = Notification(
            title=title,
            description=description,
            datetime=notification_datetime
        )
        
        db.add(new_notification)
        db.commit()
        
        return RedirectResponse(url="/admin/notifications", status_code=302)
        
    except Exception as e:
        jwt_token = request.session.get("jwt_token", "")
        return templates.TemplateResponse("notifications/add.html", {
            "request": request,
            "user": current_user,
            "error": f"Failed to add notification: {str(e)}",
            "title": title,
            "description": description,
            "datetime_str": datetime_str,
            "page_title": "Add New Notification",
            "jwt_token": jwt_token
        })

@router.get("/admin/notifications/edit/{notification_id}", response_class=HTMLResponse)
async def edit_notification_form(
    request: Request, 
    notification_id: int, 
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Show edit notification form"""
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("notifications/edit.html", {
        "request": request,
        "user": current_user,
        "user_role": current_user.role,
        "notification": notification,
        "page_title": f"Edit Notification - {notification.title}",
        "jwt_token": jwt_token
    })

@router.post("/admin/notifications/edit/{notification_id}")
async def edit_notification(
    request: Request,
    notification_id: int,
    title: str = Form(...),
    description: str = Form(...),
    datetime_str: str = Form(...),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Update notification"""
    
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    try:
        # Parse datetime
        notification_datetime = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M")
        
        notification.title = title
        notification.description = description
        notification.datetime = notification_datetime
        
        db.commit()
        
        return RedirectResponse(url="/admin/notifications", status_code=302)
        
    except Exception as e:
        jwt_token = request.session.get("jwt_token", "")
        return templates.TemplateResponse("notifications/edit.html", {
            "request": request,
            "user": current_user,
            "notification": notification,
            "error": f"Failed to update notification: {str(e)}",
            "page_title": f"Edit Notification - {notification.title}",
            "jwt_token": jwt_token
        })

@router.post("/admin/notifications/delete/{notification_id}")
async def delete_notification(
    request: Request, 
    notification_id: int, 
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Delete notification"""
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    db.delete(notification)
    db.commit()
    
    return RedirectResponse(url="/admin/notifications", status_code=302)

# ============================
# Contact Enquiry Management
# ============================

@router.get("/admin/contact-enquiries", response_class=HTMLResponse)
async def list_contact_enquiries(
    request: Request, 
    from_date: str = None,
    to_date: str = None,
    subject: str = None,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """List all contact enquiries with optional date and subject filtering"""
    # Start with base query
    query = db.query(ContactEnquiry)
    
    # Apply date filters if provided
    if from_date:
        try:
            from datetime import datetime
            from_datetime = datetime.strptime(from_date, '%Y-%m-%d')
            query = query.filter(ContactEnquiry.created_at >= from_datetime)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    if to_date:
        try:
            from datetime import datetime
            to_datetime = datetime.strptime(to_date, '%Y-%m-%d')
            # Add 1 day to include the entire to_date
            to_datetime = to_datetime.replace(hour=23, minute=59, second=59)
            query = query.filter(ContactEnquiry.created_at <= to_datetime)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    # Apply subject filter if provided
    if subject:
        if subject.lower() == 'no subject':
            query = query.filter(ContactEnquiry.subject.is_(None))
        else:
            query = query.filter(ContactEnquiry.subject == subject)
    
    enquiries = query.order_by(desc(ContactEnquiry.created_at)).all()
    
    # Get all unique subjects for the dropdown
    all_subjects = db.query(ContactEnquiry.subject).distinct().all()
    available_subjects = []
    for subj in all_subjects:
        if subj[0]:  # If subject is not None
            available_subjects.append(subj[0])
        else:
            available_subjects.append('No Subject')
    available_subjects = sorted(set(available_subjects))
    
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("contact_enquiries/list.html", {
        "request": request,
        "user": current_user,
        "user_role": current_user.role,
        "enquiries": enquiries,
        "available_subjects": available_subjects,
        "page_title": "Contact Enquiries Management",
        "jwt_token": jwt_token
    })

@router.get("/admin/contact-enquiries/view/{enquiry_id}", response_class=HTMLResponse)
async def view_contact_enquiry(
    request: Request, 
    enquiry_id: int, 
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """View contact enquiry details"""
    enquiry = db.query(ContactEnquiry).filter(ContactEnquiry.id == enquiry_id).first()
    
    if not enquiry:
        raise HTTPException(status_code=404, detail="Contact enquiry not found")
    
    jwt_token = request.session.get("jwt_token", "")
    
    return templates.TemplateResponse("contact_enquiries/view.html", {
        "request": request,
        "user": current_user,
        "user_role": current_user.role,
        "enquiry": enquiry,
        "page_title": f"Contact Enquiry - {enquiry.name}",
        "jwt_token": jwt_token
    })

@router.post("/admin/contact-enquiries/delete/{enquiry_id}")
async def delete_contact_enquiry(
    request: Request, 
    enquiry_id: int, 
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Delete contact enquiry"""
    enquiry = db.query(ContactEnquiry).filter(ContactEnquiry.id == enquiry_id).first()
    
    if not enquiry:
        raise HTTPException(status_code=404, detail="Contact enquiry not found")
    
    db.delete(enquiry)
    db.commit()
    
    return RedirectResponse(url="/admin/contact-enquiries", status_code=302)

@router.get("/admin/contact-enquiries/export")
async def export_contact_enquiries_csv(
    request: Request, 
    from_date: str = None,
    to_date: str = None,
    subject: str = None,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    """Export contact enquiries to CSV with optional date and subject filtering"""
    from fastapi.responses import StreamingResponse
    import csv
    import io
    from datetime import datetime
    
    # Start with base query (same filtering logic as list route)
    query = db.query(ContactEnquiry)
    
    # Apply date filters if provided
    if from_date:
        try:
            from_datetime = datetime.strptime(from_date, '%Y-%m-%d')
            query = query.filter(ContactEnquiry.created_at >= from_datetime)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    if to_date:
        try:
            to_datetime = datetime.strptime(to_date, '%Y-%m-%d')
            # Add 1 day to include the entire to_date
            to_datetime = to_datetime.replace(hour=23, minute=59, second=59)
            query = query.filter(ContactEnquiry.created_at <= to_datetime)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    # Apply subject filter if provided
    if subject:
        if subject.lower() == 'no subject':
            query = query.filter(ContactEnquiry.subject.is_(None))
        else:
            query = query.filter(ContactEnquiry.subject == subject)
    
    enquiries = query.order_by(desc(ContactEnquiry.created_at)).all()
    
    # Create CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write CSV headers  
    writer.writerow([
        'ID', 'Name', 'Email', 'Phone Number', 'Subject', 
        'Preferred Store', 'No of People', 'Message', 'Preferred Date/Time', 'Created At'
    ])
    
    # Write enquiry data with DD/MM/YYYY format
    for enquiry in enquiries:
        writer.writerow([
            enquiry.id,
            enquiry.name,
            enquiry.email,
            enquiry.phone_number,
            enquiry.subject or 'Contact enquiry',
            enquiry.preferred_store or '',
            enquiry.no_of_people or 1,
            enquiry.message or 'NaN',
            enquiry.preferred_date_time or '',
            enquiry.created_at.strftime('%d/%m/%Y %H:%M:%S') if enquiry.created_at else ''
        ])
    
    output.seek(0)
    
    # Generate filename with current date and filters
    current_date = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"contact_enquiries_{current_date}"
    if from_date or to_date:
        date_range = f"_{from_date or 'start'}_to_{to_date or 'end'}"
        filename += date_range
    if subject:
        subject_clean = subject.replace(' ', '_').replace('/', '_')
        filename += f"_subject_{subject_clean}"
    filename += ".csv"
    
    # Return CSV as downloadable file
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8')),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# Registered Users Management
@router.get("/admin/users", response_class=HTMLResponse)
async def list_registered_users(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_admin_auth)
):
    users = db.query(CustomerUser).filter(
        CustomerUser.is_deleted == 0
    ).order_by(desc(CustomerUser.created_at)).all()

    jwt_token = request.session.get("jwt_token", "")

    return templates.TemplateResponse("users/list.html", {
        "request": request,
        "user": current_user,
        "user_role": current_user.role,
        "users": users,
        "page_title": "Registered Users",
        "jwt_token": jwt_token
    })