from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

# Base class for all your models
Base = declarative_base()

# Create the engine once, at import time
engine = create_engine(
    settings.database_url,
            pool_size=30,          
            max_overflow=50,       
            pool_timeout=60,
            pool_pre_ping=True     
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
