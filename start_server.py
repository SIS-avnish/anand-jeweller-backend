#!/usr/bin/env python3
"""
Quick server starter with status check
"""

import uvicorn
import sys
from database import init_db

def start_server():
    """Start the FastAPI server"""
    
    print("Starting Anand Jewels Gold Rate Management System")
    print("=" * 60)
    
    # Initialize database
    print("Initializing database...")
    try:
        init_db()
        print("Database initialized successfully!")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        return
    
    print("\nAvailable Endpoints:")
    print("   Admin Dashboard: http://localhost:8000/admin")
    print("   API Documentation: http://localhost:8000/docs")
    print("   Interactive API: http://localhost:8000/redoc")
    
    print("\nDefault Login:")
    print("   Username: admin")
    print("   Password: admin123")
    
    print("\nNew API Endpoints:")
    print("   GET  /api/stores - Get all stores")
    print("   POST /api/contact-enquiries - Create enquiry")
    print("   GET  /api/contact-enquiries - Get all enquiries")
    print("   GET  /api/gold-rates/latest - Latest gold rates")
    
    print("\nAdmin Features:")
    print("   • Gold Rate Management")
    print("   • Store Management")
    print("   • Contact Enquiry Management")
    print("   • Responsive Dashboard")
    
    print("\n" + "=" * 60)
    print("Starting server on http://localhost:8000")
    print("   Press Ctrl+C to stop the server")
    print("=" * 60)
    
    # Start the server
    try:
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n\nServer stopped by user")
    except Exception as e:
        print(f"\nServer error: {e}")

if __name__ == "__main__":
    start_server()
