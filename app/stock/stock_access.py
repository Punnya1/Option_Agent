from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models import Stock


def get_all_stocks(db: Session) -> list[Stock]:
    """Return all stocks from the DB."""
    return db.scalars(select(Stock)).all()
