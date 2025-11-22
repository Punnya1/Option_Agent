# scripts/init_db_script.py
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.db.init_db import init_db

if __name__ == "__main__":
    init_db()
