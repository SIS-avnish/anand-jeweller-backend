from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

# Database URL can be overridden in .env for production.
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./gold_rates.db",
)

engine_options = {}
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_options)

# Create session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Initialize database
def init_db():
    """Create tables and seed admin user, sample stores, sample guides, and sample gold rates"""
    from models import AdminUser, Store, Guide, GoldRate
    from datetime import datetime, timedelta
    import bcrypt
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    # Create session
    db = SessionLocal()
    
    try:
        # Check if admin user exists
        admin_exists = db.query(AdminUser).filter(AdminUser.username == "admin").first()
        
        if not admin_exists:
            # Create default admin user
            password = "admin123"
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            
            admin_user = AdminUser(
                username="admin",
                password_hash=hashed_password.decode('utf-8')
            )
            
            db.add(admin_user)
            db.commit()
            print("Default admin user created (username: admin, password: admin123)")
        else:
            print("Admin user already exists")
        
        # Check if sample gold rates exist
        rates_exist = db.query(GoldRate).first()
        
        if not rates_exist:
            # Create sample gold rate entry with all three purities
            current_time = datetime.now()
            sample_rate = GoldRate(
                # 24K rates
                gold_24k_new_rate=7200.0,      # 24K selling price
                gold_24k_exchange_rate=6800.0, # 24K exchange price
                gold_24k_making_charges=800.0, # 24K making charges
                
                # 22K rates  
                gold_22k_new_rate=6600.0,      # 22K selling price
                gold_22k_exchange_rate=6200.0, # 22K exchange price
                gold_22k_making_charges=600.0, # 22K making charges
                
                # 18K rates
                gold_18k_new_rate=5400.0,      # 18K selling price
                gold_18k_exchange_rate=5000.0, # 18K exchange price
                gold_18k_making_charges=400.0, # 18K making charges
                
                release_datetime=current_time
            )
            
            db.add(sample_rate)
            db.commit()
            print("Sample gold rates created with all three purities (24K, 22K, 18K)")
        else:
            print("Gold rates already exist")
        
        # Check if stores exist
        stores_exist = db.query(Store).first()
        
        if not stores_exist:
            # Create sample stores
            sample_stores = [
                Store(
                    store_name="Anand Jewels - Main Branch",
                    store_address="123 Gold Street, Jewelry District, Mumbai - 400001",
                    store_image="/static/images/store1.jpg",
                    timings="Mon-Sat: 10:00 AM - 8:00 PM, Sun: 11:00 AM - 6:00 PM"
                ),
                Store(
                    store_name="Anand Jewels - City Center",
                    store_address="456 Diamond Plaza, City Center Mall, Mumbai - 400002",
                    store_image="/static/images/store2.jpg",
                    timings="Mon-Sun: 10:00 AM - 9:00 PM"
                ),
                Store(
                    store_name="Anand Jewels - Heritage Branch",
                    store_address="789 Heritage Road, Old City, Mumbai - 400003",
                    store_image="/static/images/store3.jpg",
                    timings="Mon-Sat: 9:30 AM - 7:30 PM, Sun: Closed"
                )
            ]
            
            for store in sample_stores:
                db.add(store)
            
            db.commit()
            print("Sample stores created successfully")
        else:
            print("Stores already exist")
        
        # Check if guides exist
        guides_exist = db.query(Guide).first()
        
        if not guides_exist:
            # Create sample guides
            sample_guides = [
                Guide(
                    title="How to Check Gold Purity",
                    content="Gold purity is measured in karats (K). 24K gold is pure gold, while 22K contains 91.7% gold and 18K contains 75% gold. Here's how to verify the purity of your gold jewelry:\n\n1. Look for hallmark stamps\n2. Check for official certification\n3. Use acid testing (professional only)\n4. Magnetic test (gold is not magnetic)\n5. Professional appraisal\n\nAlways buy from certified jewelers and ask for proper documentation.",
                    image="/static/images/guides/gold-purity-guide.jpg"
                ),
                Guide(
                    title="Understanding Gold Rate Fluctuations",
                    content="Gold rates change daily based on various factors:\n\n• International market trends\n• Currency exchange rates\n• Economic conditions\n• Demand and supply\n• Government policies\n• Festival seasons\n\nAt Anand Jewels, we update our rates daily to reflect current market conditions. Check our dashboard for the latest rates across all purities (24K, 22K, 18K).",
                    image="/static/images/guides/gold-rates-guide.jpg"
                ),
                Guide(
                    title="Gold Investment Tips",
                    content="Investing in gold can be a smart financial decision. Here are some tips:\n\n1. **Physical Gold**: Coins, bars, jewelry\n2. **Digital Gold**: Online platforms\n3. **Gold ETFs**: Exchange-traded funds\n4. **Gold Mutual Funds**: Professionally managed\n\n**Best Practices:**\n• Buy during market dips\n• Diversify your portfolio\n• Store securely\n• Keep proper documentation\n• Consider making charges\n\nVisit our stores for expert advice on gold investment.",
                    image="/static/images/guides/gold-investment-guide.jpg"
                ),
                Guide(
                    title="Jewelry Care and Maintenance",
                    content="Proper care extends the life of your gold jewelry:\n\n**Daily Care:**\n• Remove before swimming/bathing\n• Avoid contact with chemicals\n• Store separately to prevent scratches\n• Clean with soft cloth\n\n**Deep Cleaning:**\n• Use mild soap and warm water\n• Soft brush for intricate designs\n• Professional cleaning annually\n• Polish with jewelry cloth\n\n**Storage Tips:**\n• Individual pouches or compartments\n• Dry environment\n• Away from direct sunlight\n\nBring your jewelry to Anand Jewels for professional cleaning and maintenance.",
                    image="/static/images/guides/jewelry-care-guide.jpg"
                )
            ]
            
            for guide in sample_guides:
                db.add(guide)
            
            db.commit()
            print("Sample guides created successfully")
        else:
            print("Guides already exist")
            
    except Exception as e:
        print(f"Error initializing database: {e}")
        db.rollback()
    finally:
        db.close()