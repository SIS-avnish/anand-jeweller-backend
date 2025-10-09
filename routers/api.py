from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, EmailStr, Field
from datetime import timedelta
from sqlalchemy import asc
from database import get_db
from models import GoldRate, Store, ContactEnquiry, Guide, About, Team, Mission, Terms, Vision, Award, Achievement, Notification

router = APIRouter()

# Latest rates for all purities
# @router.get("/api/gold-rates/latest")
# async def get_latest_rates(db: Session = Depends(get_db)) -> Dict[str, Any]:
#     """Get the latest gold rates for all purities from consolidated structure"""
    
#     # Get the single most recent consolidated gold rate entry
#     latest_rate = db.query(GoldRate).order_by(desc(GoldRate.release_datetime)).first()
    
#     if not latest_rate:
#         return {"message": "No gold rates available"}
    
#     # Return consolidated structure with all three purities
#     return {
#         "release_datetime": latest_rate.release_datetime.strftime("%Y-%m-%d %H:%M:%S"),
#         "created_at": latest_rate.created_at.strftime("%Y-%m-%d %H:%M:%S"),
#         "gold_rates": {
#             "24K": {
#                 "selling_rate": float(latest_rate.gold_24k_new_rate),
#                 "exchange_rate": float(latest_rate.gold_24k_exchange_rate),
#                 "making_charges": float(latest_rate.gold_24k_making_charges)
#             },
#             "22K": {
#                 "selling_rate": float(latest_rate.gold_22k_new_rate),
#                 "exchange_rate": float(latest_rate.gold_22k_exchange_rate),
#                 "making_charges": float(latest_rate.gold_22k_making_charges)
#             },
#             "18K": {
#                 "selling_rate": float(latest_rate.gold_18k_new_rate),
#                 "exchange_rate": float(latest_rate.gold_18k_exchange_rate),
#                 "making_charges": float(latest_rate.gold_18k_making_charges)
#             }
#         }
#     }

from datetime import datetime
import pytz

# ... (other imports)

@router.get("/api/gold-rates/latest")
async def get_latest_rates(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get the latest gold rates for all purities from consolidated structure, excluding future dates"""
    
    # Get current time in IST
    ist = pytz.timezone('Asia/Kolkata')
    current_time = datetime.now(ist)
    
    # Get the most recent rate that is not in the future
    latest_rate = (
        db.query(GoldRate)
        .filter(GoldRate.release_datetime <= current_time)
        .order_by(desc(GoldRate.release_datetime))
        .first()
    )
    
    if not latest_rate:
        return {"message": "No gold rates available"}
    
    # Format the datetime in IST
    release_dt_ist = latest_rate.release_datetime.astimezone(ist) if latest_rate.release_datetime.tzinfo else ist.localize(latest_rate.release_datetime)
    created_at_ist = latest_rate.created_at.astimezone(ist) if latest_rate.created_at.tzinfo else ist.localize(latest_rate.created_at)
    
    # Return consolidated structure with all three purities
    return {
        "release_datetime": release_dt_ist.strftime("%Y-%m-%d %H:%M:%S %Z"),
        # "release_datetime": release_dt_ist.strftime("%Y-%m-%d"),
        "created_at": created_at_ist.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "gold_rates": {
            "24K": {
                "selling_rate": float(latest_rate.gold_24k_new_rate),
                "exchange_rate": float(latest_rate.gold_24k_exchange_rate),
                "making_charges": float(latest_rate.gold_24k_making_charges)
            },
            "22K": {
                "selling_rate": float(latest_rate.gold_22k_new_rate),
                "exchange_rate": float(latest_rate.gold_22k_exchange_rate),
                "making_charges": float(latest_rate.gold_22k_making_charges)
            },
            "18K": {
                "selling_rate": float(latest_rate.gold_18k_new_rate),
                "exchange_rate": float(latest_rate.gold_18k_exchange_rate),
                "making_charges": float(latest_rate.gold_18k_making_charges)
            }
        }
    }

# History for last N days
@router.get("/api/gold-rates/history/7d")
async def get_7_day_history(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Get consolidated gold rates history for the last 7 days including today's prices"""
    return await get_history_by_days(db, 7)

@router.get("/api/gold-rates/history/30d")
async def get_30_day_history(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Get consolidated gold rates history for the last 30 days"""
    return await get_history_by_days(db, 30)

@router.get("/api/gold-rates/history/{purity}")
async def get_history_by_purity(
    purity: str,
    days: int = Query(7, description="Number of days to look back"),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """Get gold rates history for a specific purity from consolidated structure"""
    # Validate purity
    if purity not in ["24K", "22K", "18K"]:
        raise HTTPException(status_code=400, detail="Invalid purity. Must be 24K, 22K, or 18K")
    
    # Get current time in IST
    ist = pytz.timezone('Asia/Kolkata')
    current_time = datetime.now(ist)
    start_date = (current_time - timedelta(days=days-1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Query rates for the date range - order by descending to get most recent first
    rates = (
        db.query(GoldRate)
        .filter(
            GoldRate.release_datetime >= start_date,
            GoldRate.release_datetime <= current_time
        )
        .order_by(desc(GoldRate.release_datetime))  # Changed to desc for most recent first
        .all()
    )
    
    # Format the response
    history = []
    for rate in rates:
        release_dt_ist = rate.release_datetime.astimezone(ist) if rate.release_datetime.tzinfo else ist.localize(rate.release_datetime)
        
        history.append({
            "date": release_dt_ist.strftime("%Y-%m-%d"),
            "datetime": release_dt_ist.strftime("%Y-%m-%d %H:%M:%S %Z"),
            purity: {
                "selling_rate": float(getattr(rate, f"gold_{purity.lower()}_new_rate")),
                "exchange_rate": float(getattr(rate, f"gold_{purity.lower()}_exchange_rate")),
                "making_charges": float(getattr(rate, f"gold_{purity.lower()}_making_charges"))
            }
        })
    
    return history

async def get_history_by_days(db: Session, days: int) -> List[Dict[str, Any]]:
    """Helper function to get history for a specific number of days"""
    # Get current time in IST
    ist = pytz.timezone('Asia/Kolkata')
    current_time = datetime.now(ist)
    start_date = (current_time - timedelta(days=days-1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Query rates for the date range - order by descending to get most recent first
    rates = (
        db.query(GoldRate)
        .filter(
            GoldRate.release_datetime >= start_date,
            GoldRate.release_datetime <= current_time
        )
        .order_by(desc(GoldRate.release_datetime))  # Changed to desc for most recent first
        .all()
    )
    
    # Format the response
    history = []
    for rate in rates:
        release_dt_ist = rate.release_datetime.astimezone(ist) if rate.release_datetime.tzinfo else ist.localize(rate.release_datetime)
        
        history.append({
            "date": release_dt_ist.strftime("%Y-%m-%d"),
            "datetime": release_dt_ist.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "gold_rates": {
                "24K": {
                    "selling_rate": float(rate.gold_24k_new_rate),
                    "exchange_rate": float(rate.gold_24k_exchange_rate),
                    "making_charges": float(rate.gold_24k_making_charges)
                },
                "22K": {
                    "selling_rate": float(rate.gold_22k_new_rate),
                    "exchange_rate": float(rate.gold_22k_exchange_rate),
                    "making_charges": float(rate.gold_22k_making_charges)
                },
                "18K": {
                    "selling_rate": float(rate.gold_18k_new_rate),
                    "exchange_rate": float(rate.gold_18k_exchange_rate),
                    "making_charges": float(rate.gold_18k_making_charges)
                }
            }
        })
    
    return history


async def get_history_by_days(db: Session, days: int) -> List[Dict[str, Any]]:
    """Helper function to get history for a specific number of days"""
    # Get current time in IST
    ist = pytz.timezone('Asia/Kolkata')
    current_time = datetime.now(ist)
    start_date = (current_time - timedelta(days=days-1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Query rates for the date range - order by descending to get most recent first
    rates = (
        db.query(GoldRate)
        .filter(
            GoldRate.release_datetime >= start_date,
            GoldRate.release_datetime <= current_time
        )
        .order_by(desc(GoldRate.release_datetime))  # Most recent first
        .all()
    )
    
    # Format the response
    history = []
    for rate in rates:
        release_dt_ist = rate.release_datetime.astimezone(ist) if rate.release_datetime.tzinfo else ist.localize(rate.release_datetime)
        
        history.append({
            "date": release_dt_ist.strftime("%Y-%m-%d"),
            "datetime": release_dt_ist.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "gold_rates": {
                "24K": {
                    "selling_rate": float(rate.gold_24k_new_rate),
                    "exchange_rate": float(rate.gold_24k_exchange_rate),
                    "making_charges": float(rate.gold_24k_making_charges)
                },
                "22K": {
                    "selling_rate": float(rate.gold_22k_new_rate),
                    "exchange_rate": float(rate.gold_22k_exchange_rate),
                    "making_charges": float(rate.gold_22k_making_charges)
                },
                "18K": {
                    "selling_rate": float(rate.gold_18k_new_rate),
                    "exchange_rate": float(rate.gold_18k_exchange_rate),
                    "making_charges": float(rate.gold_18k_making_charges)
                }
            }
        })
    
    return history



# History filtered by purity
# @router.get("/api/gold-rates/history/{purity}")
# async def get_history_by_purity(
#     purity: str,
#     days: int = Query(7, description="Number of days to look back"),
#     db: Session = Depends(get_db)
# ) -> List[Dict[str, Any]]:
#     """Get gold rates history for a specific purity from consolidated structure"""
    
#     # Validate purity
#     if purity not in ["24K", "22K", "18K"]:
#         raise HTTPException(status_code=400, detail="Invalid purity. Must be 24K, 22K, or 18K")
    
#     # Calculate date range - ensure we include today's full day
#     end_date = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
#     start_date = (end_date - timedelta(days=days-1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
#     # Query consolidated rates within date range
#     rates = db.query(GoldRate).filter(
#         and_(
#             GoldRate.release_datetime >= start_date,
#             GoldRate.release_datetime <= end_date
#         )
#     ).order_by(desc(GoldRate.release_datetime)).all()
    
#     # Extract data for the specific purity from consolidated records
#     purity_history = []
#     for rate in rates:
#         if purity == "24K":
#             purity_data = {
#                 "purity": "24K",
#                 "selling_rate": float(rate.gold_24k_new_rate),
#                 "exchange_rate": float(rate.gold_24k_exchange_rate),
#                 "making_charges": float(rate.gold_24k_making_charges),
#                 "release_datetime": rate.release_datetime.strftime("%Y-%m-%d %H:%M:%S")
#             }
#         elif purity == "22K":
#             purity_data = {
#                 "purity": "22K",
#                 "selling_rate": float(rate.gold_22k_new_rate),
#                 "exchange_rate": float(rate.gold_22k_exchange_rate),
#                 "making_charges": float(rate.gold_22k_making_charges),
#                 "release_datetime": rate.release_datetime.strftime("%Y-%m-%d %H:%M:%S")
#             }
#         else:  # 18K
#             purity_data = {
#                 "purity": "18K",
#                 "selling_rate": float(rate.gold_18k_new_rate),
#                 "exchange_rate": float(rate.gold_18k_exchange_rate),
#                 "making_charges": float(rate.gold_18k_making_charges),
#                 "release_datetime": rate.release_datetime.strftime("%Y-%m-%d %H:%M:%S")
#             }
#         purity_history.append(purity_data)
    
#     return purity_history




# Helper function for history queries
# async def get_history_by_days(db: Session, days: int) -> List[Dict[str, Any]]:
#     """Get consolidated gold rates history for the specified number of days including today"""
    
#     # Calculate date range - ensure we include today's full day
#     end_date = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
#     start_date = (end_date - timedelta(days=days-1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
#     # Query all consolidated rates within date range
#     rates = db.query(GoldRate).filter(
#         and_(
#             GoldRate.release_datetime >= start_date,
#             GoldRate.release_datetime <= end_date
#         )
#     ).order_by(desc(GoldRate.release_datetime)).all()
    
#     # Convert each consolidated rate to the response format
#     return [
#         {
#             "release_datetime": rate.release_datetime.strftime("%Y-%m-%d %H:%M:%S"),
#             "created_at": rate.created_at.strftime("%Y-%m-%d %H:%M:%S"),
#             "gold_rates": {
#                 "24K": {
#                     "selling_rate": float(rate.gold_24k_new_rate),
#                     "exchange_rate": float(rate.gold_24k_exchange_rate),
#                     "making_charges": float(rate.gold_24k_making_charges)
#                 },
#                 "22K": {
#                     "selling_rate": float(rate.gold_22k_new_rate),
#                     "exchange_rate": float(rate.gold_22k_exchange_rate),
#                     "making_charges": float(rate.gold_22k_making_charges)
#                 },
#                 "18K": {
#                     "selling_rate": float(rate.gold_18k_new_rate),
#                     "exchange_rate": float(rate.gold_18k_exchange_rate),
#                     "making_charges": float(rate.gold_18k_making_charges)
#                 }
#             }
#         }
#         for rate in rates
#     ]

# Additional endpoint for getting all available purities
@router.get("/api/gold-rates/purities")
async def get_available_purities() -> List[str]:
    """Get list of available gold purities"""
    return ["24K", "22K", "18K"]

# New endpoint for simplified current rates
@router.get("/api/gold-rates/current")
async def get_current_rates_simple(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get current gold rates in simplified format"""
    
    latest_rate = db.query(GoldRate).order_by(desc(GoldRate.release_datetime)).first()
    
    if not latest_rate:
        return {"message": "No gold rates available"}
    
    return {
        "last_updated": latest_rate.release_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "rates": {
            "24k_gold": {
                "selling": float(latest_rate.gold_24k_new_rate),
                "exchange": float(latest_rate.gold_24k_exchange_rate),
                "making": float(latest_rate.gold_24k_making_charges)
            },
            "22k_gold": {
                "selling": float(latest_rate.gold_22k_new_rate),
                "exchange": float(latest_rate.gold_22k_exchange_rate),
                "making": float(latest_rate.gold_22k_making_charges)
            },
            "18k_gold": {
                "selling": float(latest_rate.gold_18k_new_rate),
                "exchange": float(latest_rate.gold_18k_exchange_rate),
                "making": float(latest_rate.gold_18k_making_charges)
            }
        }
    }

# Endpoint to get all historical records (paginated)
@router.get("/api/gold-rates/all")
async def get_all_rates(
    page: int = Query(1, description="Page number (1-based)"),
    limit: int = Query(10, description="Number of records per page"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get all gold rate records with pagination"""
    
    # Calculate offset
    offset = (page - 1) * limit
    
    # Get total count
    total_count = db.query(GoldRate).count()
    
    # Get paginated records
    rates = db.query(GoldRate).order_by(
        desc(GoldRate.release_datetime)
    ).offset(offset).limit(limit).all()
    
    # Calculate pagination info
    total_pages = (total_count + limit - 1) // limit
    has_next = page < total_pages
    has_previous = page > 1
    
    return {
        "pagination": {
            "current_page": page,
            "total_pages": total_pages,
            "total_records": total_count,
            "records_per_page": limit,
            "has_next": has_next,
            "has_previous": has_previous
        },
        "data": [
            {
                "id": rate.id,
                "release_datetime": rate.release_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                "created_at": rate.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "gold_rates": {
                    "24K": {
                        "selling_rate": float(rate.gold_24k_new_rate),
                        "exchange_rate": float(rate.gold_24k_exchange_rate),
                        "making_charges": float(rate.gold_24k_making_charges)
                    },
                    "22K": {
                        "selling_rate": float(rate.gold_22k_new_rate),
                        "exchange_rate": float(rate.gold_22k_exchange_rate),
                        "making_charges": float(rate.gold_22k_making_charges)
                    },
                    "18K": {
                        "selling_rate": float(rate.gold_18k_new_rate),
                        "exchange_rate": float(rate.gold_18k_exchange_rate),
                        "making_charges": float(rate.gold_18k_making_charges)
                    }
                }
            }
            for rate in rates
        ]
    }

# Pydantic models for request/response
class ContactEnquiryCreate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Customer's full name")
    phone_number: str = Field(..., min_length=10, max_length=15, description="Phone number with country code")
    email: Optional[str] = Field(None, max_length=100, description="Email address (if available)")
    subject: Optional[str] = Field("Contact enquiry", max_length=200, description="Subject of the enquiry")
    preferred_store: Optional[str] = Field(None, min_length=5, max_length=200, description="Name of preferred store")
    preferred_date_time: Optional[str] = Field(None, min_length=10, max_length=100, description="Preferred appointment date and time")
    no_of_people: Optional[int] = Field(1, ge=1, le=50, description="Number of people for the appointment")
    message: Optional[str] = Field("NaN", max_length=1000, description="Additional message or requirements")

class ContactEnquiryResponse(BaseModel):
    id: int
    name: str
    phone_number: str
    email: str
    subject: Optional[str]
    preferred_store: str
    preferred_date_time: str
    no_of_people: Optional[int]
    message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True

class StoreResponse(BaseModel):
    id: int
    store_name: str
    phone_number: Optional[str]
    store_address: str
    store_image: Optional[str]
    youtube_link: Optional[str]
    map_link: Optional[str]
    timings: str
    created_at: datetime

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True

class GuideResponse(BaseModel):
    id: int
    title: str
    content: str
    image: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True

class AboutResponse(BaseModel):
    id: int
    title: str
    content: str
    image: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True

class TeamResponse(BaseModel):
    id: int
    position: str
    name: str
    content: str
    image: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True

class MissionResponse(BaseModel):
    id: int
    title: str
    content: str
    image: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True

class TermsResponse(BaseModel):
    id: int
    title: str
    content: str
    image: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True

class VisionResponse(BaseModel):
    id: int
    title: str
    content: str
    image: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True

class AwardResponse(BaseModel):
    id: int
    title: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True

class AchievementResponse(BaseModel):
    id: int
    title: str
    date: datetime
    content: str
    image: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True

class NotificationResponse(BaseModel):
    id: int
    title: str
    description: str
    datetime: datetime
    created_at: datetime

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True

# Store Management APIs
@router.get("/api/stores", response_model=List[StoreResponse])
async def get_all_stores(db: Session = Depends(get_db)):
    """Get all store locations"""
    stores = db.query(Store).order_by(Store.created_at.desc()).all()
    return stores

@router.get("/api/stores/{store_id}", response_model=StoreResponse)
async def get_store_by_id(store_id: int, db: Session = Depends(get_db)):
    """Get a specific store by ID"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return store

# Contact Enquiry APIs
@router.post("/api/contact-enquiries", response_model=ContactEnquiryResponse)
async def create_contact_enquiry(
    enquiry: ContactEnquiryCreate,
    db: Session = Depends(get_db)
):
    """Create a new contact enquiry"""
    
    # Validate that the preferred store exists
    store_exists = db.query(Store).filter(Store.store_name == enquiry.preferred_store).first()
    if not store_exists:
        # Get all available stores for error message
        available_stores = db.query(Store).all()
        store_names = [store.store_name for store in available_stores]
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid store name. Available stores: {', '.join(store_names)}"
        )
    
    # Create new contact enquiry
    db_enquiry = ContactEnquiry(
        name=enquiry.name,
        phone_number=enquiry.phone_number,
        email=enquiry.email,
        subject=enquiry.subject,
        preferred_store=enquiry.preferred_store,
        preferred_date_time=enquiry.preferred_date_time,
        no_of_people=enquiry.no_of_people,
        message=enquiry.message
    )
    
    db.add(db_enquiry)
    db.commit()
    db.refresh(db_enquiry)
    
    return db_enquiry

@router.get("/api/contact-enquiries", response_model=List[ContactEnquiryResponse])
async def get_all_contact_enquiries(
    limit: int = Query(50, description="Maximum number of enquiries to return"),
    db: Session = Depends(get_db)
):
    """Get all contact enquiries (limited for performance)"""
    enquiries = db.query(ContactEnquiry).order_by(
        desc(ContactEnquiry.created_at)
    ).limit(limit).all()
    return enquiries

@router.get("/api/contact-enquiries/{enquiry_id}", response_model=ContactEnquiryResponse)
async def get_contact_enquiry_by_id(enquiry_id: int, db: Session = Depends(get_db)):
    """Get a specific contact enquiry by ID"""
    enquiry = db.query(ContactEnquiry).filter(ContactEnquiry.id == enquiry_id).first()
    if not enquiry:
        raise HTTPException(status_code=404, detail="Contact enquiry not found")
    return enquiry

# Guide APIs
@router.get("/api/guides", response_model=List[GuideResponse])
async def get_all_guides(
    limit: int = Query(20, description="Maximum number of guides to return"),
    db: Session = Depends(get_db)
):
    """Get all guides"""
    guides = db.query(Guide).order_by(desc(Guide.created_at)).limit(limit).all()
    return guides

@router.get("/api/guides/{guide_id}", response_model=GuideResponse)
async def get_guide_by_id(guide_id: int, db: Session = Depends(get_db)):
    """Get a specific guide by ID"""
    guide = db.query(Guide).filter(Guide.id == guide_id).first()
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")
    return guide

# About APIs
@router.get("/api/about", response_model=List[AboutResponse])
async def get_all_about_public(
    limit: int = Query(20, description="Maximum number of about entries to return"),
    db: Session = Depends(get_db)
):
    """Get all about entries (public access)"""
    about_entries = db.query(About).order_by(desc(About.created_at)).limit(limit).all()
    return about_entries

@router.get("/api/about/{about_id}", response_model=AboutResponse)
async def get_about_by_id_public(about_id: int, db: Session = Depends(get_db)):
    """Get a specific about entry by ID (public access)"""
    about = db.query(About).filter(About.id == about_id).first()
    if not about:
        raise HTTPException(status_code=404, detail="About entry not found")
    return about

# Team APIs
@router.get("/api/team", response_model=List[TeamResponse])
async def get_all_team_public(
    limit: int = Query(20, description="Maximum number of team entries to return"),
    db: Session = Depends(get_db)
):
    """Get all team entries (public access)"""
    team_entries = db.query(Team).order_by(desc(Team.created_at)).limit(limit).all()
    return team_entries

@router.get("/api/team/{team_id}", response_model=TeamResponse)
async def get_team_by_id_public(team_id: int, db: Session = Depends(get_db)):
    """Get a specific team entry by ID (public access)"""
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team entry not found")
    return team

# Mission APIs
@router.get("/api/missions", response_model=List[MissionResponse])
async def get_all_missions_public(
    limit: int = Query(20, description="Maximum number of mission entries to return"),
    db: Session = Depends(get_db)
):
    """Get all mission entries (public access)"""
    mission_entries = db.query(Mission).order_by(desc(Mission.created_at)).limit(limit).all()
    return mission_entries

@router.get("/api/missions/{mission_id}", response_model=MissionResponse)
async def get_mission_by_id_public(mission_id: int, db: Session = Depends(get_db)):
    """Get a specific mission entry by ID (public access)"""
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission entry not found")
    return mission

# Terms APIs
@router.get("/api/terms", response_model=List[TermsResponse])
async def get_all_terms_public(
    limit: int = Query(20, description="Maximum number of terms entries to return"),
    db: Session = Depends(get_db)
):
    """Get all terms entries (public access)"""
    terms_entries = db.query(Terms).order_by(desc(Terms.created_at)).limit(limit).all()
    return terms_entries

@router.get("/api/terms/{terms_id}", response_model=TermsResponse)
async def get_terms_by_id_public(terms_id: int, db: Session = Depends(get_db)):
    """Get a specific terms entry by ID (public access)"""
    terms = db.query(Terms).filter(Terms.id == terms_id).first()
    if not terms:
        raise HTTPException(status_code=404, detail="Terms entry not found")
    return terms

# Vision Management APIs
@router.get("/api/visions", response_model=List[VisionResponse])
async def get_all_visions_public(
    limit: int = Query(20, description="Maximum number of vision entries to return"),
    db: Session = Depends(get_db)
):
    """Get all vision entries (public access)"""
    vision_entries = db.query(Vision).order_by(desc(Vision.created_at)).limit(limit).all()
    return vision_entries

@router.get("/api/visions/{vision_id}", response_model=VisionResponse)
async def get_vision_by_id_public(vision_id: int, db: Session = Depends(get_db)):
    """Get a specific vision entry by ID (public access)"""
    vision = db.query(Vision).filter(Vision.id == vision_id).first()
    if not vision:
        raise HTTPException(status_code=404, detail="Vision entry not found")
    return vision

# Awards API endpoints
@router.get("/api/awards", response_model=List[AwardResponse])
async def get_all_awards_public(
    limit: int = Query(20, description="Maximum number of awards to return"),
    db: Session = Depends(get_db)
):
    """Get all awards (public access)"""
    awards = db.query(Award).order_by(desc(Award.id)).limit(limit).all()
    return awards

@router.get("/api/awards/{award_id}", response_model=AwardResponse)
async def get_award_by_id_public(award_id: int, db: Session = Depends(get_db)):
    """Get a specific award by ID (public access)"""
    award = db.query(Award).filter(Award.id == award_id).first()
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    return award

# Achievements API endpoints
@router.get("/api/achievements", response_model=List[AchievementResponse])
async def get_all_achievements_public(
    limit: int = Query(20, description="Maximum number of achievements to return"),
    db: Session = Depends(get_db)
):
    """Get all achievements (public access)"""
    achievements = db.query(Achievement).order_by(desc(Achievement.date)).limit(limit).all()
    return achievements

@router.get("/api/achievements/{achievement_id}", response_model=AchievementResponse)
async def get_achievement_by_id_public(achievement_id: int, db: Session = Depends(get_db)):
    """Get a specific achievement by ID (public access)"""
    achievement = db.query(Achievement).filter(Achievement.id == achievement_id).first()
    if not achievement:
        raise HTTPException(status_code=404, detail="Achievement not found")
    return achievement

# Notifications API endpoints
@router.get("/api/notifications", response_model=List[NotificationResponse])
async def get_all_notifications_public(
    limit: int = Query(20, description="Maximum number of notifications to return"),
    db: Session = Depends(get_db)
):
    """Get all notifications (public access)"""
    notifications = db.query(Notification).order_by(desc(Notification.datetime)).limit(limit).all()
    return notifications

@router.get("/api/notifications/{notification_id}", response_model=NotificationResponse)
async def get_notification_by_id_public(notification_id: int, db: Session = Depends(get_db)):
    """Get a specific notification by ID (public access)"""
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notification

# API Documentation endpoint
@router.get("/api")
async def api_documentation():
    """Get comprehensive API documentation with all available endpoints"""
    return {
        "api_name": "Anand Jewels Public API",
        "version": "1.0.0",
        "description": "Complete public API for Anand Jewels gold rates, stores, and content management",
        "base_url": "/api",
        "endpoints": {
            "gold_rates": {
                "description": "Gold rate management endpoints",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/gold-rates/latest",
                        "description": "Get the latest gold rates for all purities (24K, 22K, 18K)"
                    },
                    {
                        "method": "GET",
                        "path": "/api/gold-rates/current",
                        "description": "Get current gold rates in simplified format"
                    },
                    {
                        "method": "GET",
                        "path": "/api/gold-rates/history/7d",
                        "description": "Get 7-day gold rate history"
                    },
                    {
                        "method": "GET",
                        "path": "/api/gold-rates/history/30d",
                        "description": "Get 30-day gold rate history"
                    },
                    {
                        "method": "GET",
                        "path": "/api/gold-rates/history/{purity}",
                        "description": "Get history for specific purity (24K/22K/18K)",
                        "parameters": ["purity", "days (optional)"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/gold-rates/all",
                        "description": "Get all gold rates with pagination",
                        "parameters": ["page", "limit"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/gold-rates/purities",
                        "description": "Get list of available gold purities"
                    }
                ]
            },
            "stores": {
                "description": "Store location and information endpoints",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/stores",
                        "description": "Get all store locations with complete details",
                        "response_fields": [
                            "id", "store_name", "phone_number", "store_address", 
                            "store_image", "youtube_link", "map_link", "timings", "created_at"
                        ]
                    },
                    {
                        "method": "GET",
                        "path": "/api/stores/{store_id}",
                        "description": "Get specific store by ID",
                        "parameters": ["store_id"]
                    }
                ]
            },
            "contact_enquiries": {
                "description": "Customer contact and enquiry management",
                "endpoints": [
                    {
                        "method": "POST",
                        "path": "/api/contact-enquiries",
                        "description": "Create new contact enquiry",
                        "required_fields": ["name", "phone_number", "email", "preferred_store", "preferred_date_time"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/contact-enquiries",
                        "description": "Get all contact enquiries",
                        "parameters": ["limit (optional)"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/contact-enquiries/{enquiry_id}",
                        "description": "Get specific enquiry by ID",
                        "parameters": ["enquiry_id"]
                    }
                ]
            },
            "content_management": {
                "description": "Website content management endpoints",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/about",
                        "description": "Get all about us entries",
                        "response_fields": ["id", "title", "content", "image", "created_at"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/about/{about_id}",
                        "description": "Get specific about entry by ID"
                    },
                    {
                        "method": "GET",
                        "path": "/api/team",
                        "description": "Get all team member entries",
                        "response_fields": ["id", "position", "name", "content", "image", "created_at"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/team/{team_id}",
                        "description": "Get specific team member by ID"
                    },
                    {
                        "method": "GET",
                        "path": "/api/missions",
                        "description": "Get all mission/vision entries",
                        "response_fields": ["id", "title", "content", "image", "created_at"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/missions/{mission_id}",
                        "description": "Get specific mission by ID"
                    },
                    {
                        "method": "GET",
                        "path": "/api/terms",
                        "description": "Get all terms & conditions entries",
                        "response_fields": ["id", "title", "content", "image", "created_at"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/terms/{terms_id}",
                        "description": "Get specific terms entry by ID"
                    },
                    {
                        "method": "GET",
                        "path": "/api/guides",
                        "description": "Get all guide entries",
                        "response_fields": ["id", "title", "content", "image", "created_at"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/guides/{guide_id}",
                        "description": "Get specific guide by ID"
                    },
                    {
                        "method": "GET",
                        "path": "/api/visions",
                        "description": "Get all vision entries",
                        "response_fields": ["id", "title", "content", "image", "created_at"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/visions/{vision_id}",
                        "description": "Get specific vision entry by ID"
                    },
                    {
                        "method": "GET",
                        "path": "/api/awards",
                        "description": "Get all award entries",
                        "response_fields": ["id", "title", "content"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/awards/{award_id}",
                        "description": "Get specific award by ID"
                    },
                    {
                        "method": "GET",
                        "path": "/api/achievements",
                        "description": "Get all achievement entries",
                        "response_fields": ["id", "title", "date", "content", "image"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/achievements/{achievement_id}",
                        "description": "Get specific achievement by ID"
                    },
                    {
                        "method": "GET",
                        "path": "/api/notifications",
                        "description": "Get all notification entries",
                        "response_fields": ["id", "title", "description", "datetime"]
                    },
                    {
                        "method": "GET",
                        "path": "/api/notifications/{notification_id}",
                        "description": "Get specific notification by ID"
                    }
                ]
            },
            "utility": {
                "description": "Utility and system endpoints",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/health",
                        "description": "API health check"
                    },
                    {
                        "method": "GET",
                        "path": "/api",
                        "description": "This API documentation endpoint"
                    }
                ]
            }
        },
        "response_formats": {
            "success": "JSON with requested data",
            "error": "JSON with error message and status code",
            "pagination": "Includes pagination metadata when applicable"
        },
        "authentication": "No authentication required for public endpoints",
        "rate_limiting": "No rate limiting currently implemented",
        "last_updated": datetime.now().isoformat()
    }

# Health check endpoint
@router.get("/api/health")
async def health_check():
    """API health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}