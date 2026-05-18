from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

# Import routers
from routers import admin, api, stores, admin_api

# Import database initialization
from database import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting up Gold Rate Management System...")
    init_db()
    print("Database initialized successfully!")
    yield
    # Shutdown
    print("Shutting down...")

# Create FastAPI app
app = FastAPI(
    title="Gold Rate Management System",
    description="A comprehensive MVP for managing gold rates with admin dashboard and public API",
    version="1.0.0",
    lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Add session middleware for authentication
# In production, use a secure secret key
SECRET_KEY = "your-secret-key-change-this-in-production"
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400)  # 24 hours

# Mount static files for custom CSS/JS
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(admin.router, tags=["Admin Dashboard"])
app.include_router(admin_api.router, tags=["Admin API (JWT)"])
app.include_router(stores.router, tags=["Store Management"])
app.include_router(api.router, tags=["Public API"])
@app.get("/")
async def root():
    """Redirect root to admin login"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin")

# Health check
@app.get("/health")
async def health_check():
    """Application health check"""
    return {
        "status": "healthy",
        "application": "Gold Rate Management System",
        "version": "1.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    
    print("🚀 Starting Gold Rate Management System")
    print("📊 Admin Dashboard: http://localhost:8000/admin")
    print("🔌 API Documentation: http://localhost:8000/docs")
    print("💾 Default admin credentials: admin / admin123")
    
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        log_level="info"
    )