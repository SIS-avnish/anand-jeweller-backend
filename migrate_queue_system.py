#!/usr/bin/env python3
"""
Migration script for Queue Management System.
Adds city column to stores table, store_id to admin_users table, and creates queue_entries table.
"""

import sqlite3
import os
import sys

# Add current directory to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import engine, Base
import models

def run_migration():
    db_path = "gold_rates.db"
    
    if not os.path.exists(db_path):
        print(f"❌ Database file {db_path} not found!")
        return False
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("Starting Queue System Database Migration...")
        
        # 1. Add city column to stores if it doesn't exist
        cursor.execute("PRAGMA table_info(stores)")
        store_columns = [col[1] for col in cursor.fetchall()]
        
        if "city" not in store_columns:
            print("Adding 'city' column to 'stores' table...")
            cursor.execute("ALTER TABLE stores ADD COLUMN city VARCHAR NOT NULL DEFAULT 'Indore'")
            conn.commit()
            print("✅ 'city' column added to 'stores'.")
        else:
            print("ℹ️ 'city' column already exists in 'stores'.")
            
        # 2. Update city names for existing stores based on their store_name
        print("Updating city names for existing stores...")
        cursor.execute("SELECT id, store_name FROM stores")
        stores = cursor.fetchall()
        for store_id, name in stores:
            city = "Indore"
            if "Bhopal" in name:
                city = "Bhopal"
            elif "Raipur" in name:
                city = "Raipur"
            
            cursor.execute("UPDATE stores SET city = ? WHERE id = ?", (city, store_id))
            print(f"  Mapped store '{name.strip()}' (ID: {store_id}) to City: '{city}'")
        conn.commit()
        
        # 3. Add store_id column to admin_users if it doesn't exist
        cursor.execute("PRAGMA table_info(admin_users)")
        admin_columns = [col[1] for col in cursor.fetchall()]
        
        if "store_id" not in admin_columns:
            print("Adding 'store_id' column to 'admin_users' table...")
            cursor.execute("ALTER TABLE admin_users ADD COLUMN store_id INTEGER")
            conn.commit()
            print("✅ 'store_id' column added to 'admin_users'.")
        else:
            print("ℹ️ 'store_id' column already exists in 'admin_users'.")
            
        conn.close()
        
        # 4. Create queue_entries table using SQLAlchemy Base metadata
        print("Creating queue_entries table via SQLAlchemy...")
        Base.metadata.create_all(bind=engine)
        print("✅ SQLAlchemy tables initialized.")
        
        print("\n🎉 Migration completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

if __name__ == "__main__":
    run_migration()
