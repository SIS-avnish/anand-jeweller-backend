from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models import Store, ContactEnquiry, Guide
from routers.admin import get_current_user
from datetime import datetime
import os
import uuid
from pathlib import Path

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")

# Helper function for file uploads
async def save_uploaded_file(file: UploadFile, upload_dir: str) -> str:
    """Save uploaded file and return the file path"""
    if not file.filename:
        return None
    
    # Create upload directory if it doesn't exist
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    
    # Generate unique filename
    file_extension = Path(file.filename).suffix
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = Path(upload_dir) / unique_filename
    
    # Save file
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
    
    # Return web path - adjust based on upload directory
    if "stores" in upload_dir:
        return f"/static/uploads/stores/{unique_filename}"
    else:
        return f"/static/images/guides/{unique_filename}"

# Store Management Routes

@router.get("/stores")
async def list_stores(request: Request, db: Session = Depends(get_db)):
    """List all stores"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    stores = db.query(Store).order_by(Store.created_at.desc()).all()
    
    return templates.TemplateResponse("stores/list.html", {
        "request": request,
        "user": user,
        "user_role": user.role,
        "stores": stores
    })

@router.get("/stores/add")
async def add_store_form(request: Request, db: Session = Depends(get_db)):
    """Show add store form"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    return templates.TemplateResponse("stores/add.html", {
        "request": request,
        "user": user,
        "user_role": user.role
    })

@router.post("/stores/add")
async def add_store(
    request: Request,
    store_name: str = Form(...),
    city: str = Form("Indore"),
    phone_number: str = Form(""),
    store_address: str = Form(...),
    store_image: UploadFile = File(None),
    youtube_link: str = Form(""),
    map_link: str = Form(""),
    timings: str = Form(...),
    db: Session = Depends(get_db)
):
    """Add new store"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Handle file upload for store image
        image_path = None
        if store_image and store_image.filename:
            image_path = await save_uploaded_file(store_image, "static/uploads/stores")
        
        new_store = Store(
            store_name=store_name,
            city=city.strip() if city else "Indore",
            phone_number=phone_number if phone_number else None,
            store_address=store_address,
            store_image=image_path,
            youtube_link=youtube_link if youtube_link else None,
            map_link=map_link if map_link else None,
            timings=timings
        )
        
        db.add(new_store)
        db.commit()
        
        return RedirectResponse(url="/admin/stores", status_code=302)
        
    except Exception as e:
        return templates.TemplateResponse("stores/add.html", {
            "request": request,
            "user": user,
            "user_role": user.role,
            "error": f"Error adding store: {str(e)}"
        })

@router.get("/stores/edit/{store_id}")
async def edit_store_form(request: Request, store_id: int, db: Session = Depends(get_db)):
    """Show edit store form"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    return templates.TemplateResponse("stores/edit.html", {
        "request": request,
        "user": user,
        "user_role": user.role,
        "store": store
    })

@router.post("/stores/edit/{store_id}")
async def edit_store(
    request: Request,
    store_id: int,
    store_name: str = Form(...),
    city: str = Form("Indore"),
    phone_number: str = Form(""),
    store_address: str = Form(...),
    store_image: UploadFile = File(None),
    youtube_link: str = Form(""),
    map_link: str = Form(""),
    timings: str = Form(...),
    db: Session = Depends(get_db)
):
    """Update store"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        store = db.query(Store).filter(Store.id == store_id).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        # Handle file upload - only update image if new file is uploaded
        if store_image and store_image.filename:
            image_path = await save_uploaded_file(store_image, "static/uploads/stores")
            store.store_image = image_path
        
        store.store_name = store_name
        store.city = city.strip() if city else "Indore"
        store.phone_number = phone_number if phone_number else None
        store.store_address = store_address
        store.youtube_link = youtube_link if youtube_link else None
        store.map_link = map_link if map_link else None
        store.timings = timings
        
        db.commit()
        
        return RedirectResponse(url="/admin/stores", status_code=302)
        
    except Exception as e:
        store = db.query(Store).filter(Store.id == store_id).first()
        return templates.TemplateResponse("stores/edit.html", {
            "request": request,
            "user": user,
            "user_role": user.role,
            "store": store,
            "error": f"Error updating store: {str(e)}"
        })

@router.get("/stores/delete/{store_id}")
async def delete_store(request: Request, store_id: int, db: Session = Depends(get_db)):
    """Delete store"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        store = db.query(Store).filter(Store.id == store_id).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        db.delete(store)
        db.commit()
        
        return RedirectResponse(url="/admin/stores", status_code=302)
        
    except Exception as e:
        return RedirectResponse(url="/admin/stores?error=delete_failed", status_code=302)

# Guide Management Routes

@router.get("/guides")
async def list_guides(request: Request, db: Session = Depends(get_db)):
    """List all guides"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    guides = db.query(Guide).order_by(Guide.created_at.desc()).all()
    
    return templates.TemplateResponse("guides/list.html", {
        "request": request,
        "user": user,
        "user_role": user.role,
        "guides": guides
    })

@router.get("/guides/add")
async def add_guide_form(request: Request, db: Session = Depends(get_db)):
    """Show add guide form"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    return templates.TemplateResponse("guides/add.html", {
        "request": request,
        "user": user,
        "user_role": user.role
    })

@router.post("/guides/add")
async def add_guide(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    image_file: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    """Add new guide"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Handle file upload
        image_path = None
        if image_file and image_file.filename:
            upload_dir = "static/images/guides"
            image_path = await save_uploaded_file(image_file, upload_dir)
        
        new_guide = Guide(
            title=title,
            content=content,
            image=image_path
        )
        
        db.add(new_guide)
        db.commit()
        
        return RedirectResponse(url="/admin/guides", status_code=302)
        
    except Exception as e:
        return templates.TemplateResponse("guides/add.html", {
            "request": request,
            "user": user,
            "user_role": user.role,
            "error": f"Error adding guide: {str(e)}"
        })

@router.get("/guides/edit/{guide_id}")
async def edit_guide_form(request: Request, guide_id: int, db: Session = Depends(get_db)):
    """Show edit guide form"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    guide = db.query(Guide).filter(Guide.id == guide_id).first()
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")
    
    return templates.TemplateResponse("guides/edit.html", {
        "request": request,
        "user": user,
        "user_role": user.role,
        "guide": guide
    })

@router.post("/guides/edit/{guide_id}")
async def edit_guide(
    request: Request,
    guide_id: int,
    title: str = Form(...),
    content: str = Form(...),
    image_file: UploadFile = File(None),
    keep_current_image: str = Form(None),
    db: Session = Depends(get_db)
):
    """Update guide"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        guide = db.query(Guide).filter(Guide.id == guide_id).first()
        if not guide:
            raise HTTPException(status_code=404, detail="Guide not found")
        
        guide.title = title
        guide.content = content
        
        # Handle image upload
        if image_file and image_file.filename:
            # New image uploaded
            upload_dir = "static/images/guides"
            new_image_path = await save_uploaded_file(image_file, upload_dir)
            guide.image = new_image_path
        elif not keep_current_image:
            # Remove current image if not keeping it and no new image uploaded
            guide.image = None
        # If keep_current_image is checked, don't change the image
        
        db.commit()
        
        return RedirectResponse(url="/admin/guides", status_code=302)
        
    except Exception as e:
        return templates.TemplateResponse("guides/edit.html", {
            "request": request,
            "user": user,
            "user_role": user.role,
            "guide": guide,
            "error": f"Error updating guide: {str(e)}"
        })

@router.get("/guides/delete/{guide_id}")
async def delete_guide(request: Request, guide_id: int, db: Session = Depends(get_db)):
    """Delete guide"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        guide = db.query(Guide).filter(Guide.id == guide_id).first()
        if not guide:
            raise HTTPException(status_code=404, detail="Guide not found")
        
        db.delete(guide)
        db.commit()
        
        return RedirectResponse(url="/admin/guides", status_code=302)
        
    except Exception as e:
        return RedirectResponse(url="/admin/guides?error=delete_failed", status_code=302)


