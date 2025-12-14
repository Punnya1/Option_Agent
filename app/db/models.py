from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Date,
    DateTime,
    Boolean,
    JSON,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.sessions import Base

class ProcessedRun(Base):
    __tablename__ = "processed_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_date = Column(Date, nullable=False, unique=True)  # trading date that was ingested
    source = Column(String, nullable=False)  # e.g., "equity", "fno", "both"
    created_at = Column(Date, server_default=func.now())

class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(32), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    segment = Column(String(32), nullable=True)  # e.g. EQ

    # relationships if needed later
    prices = relationship("DailyPrice", back_populates="stock", cascade="all, delete-orphan")
    options = relationship("OptionChain", back_populates="stock", cascade="all, delete-orphan")


class DailyPrice(Base):
    __tablename__ = "daily_prices"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), ForeignKey("stocks.symbol"), index=True, nullable=False)
    date = Column(Date, index=True, nullable=False)

    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=True)  # can be big, keep as float

    stock = relationship("Stock", back_populates="prices")

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_daily_price_symbol_date"),
        Index("ix_daily_prices_symbol_date", "symbol", "date"),
    )


class OptionChain(Base):
    __tablename__ = "option_chain"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), ForeignKey("stocks.symbol"), index=True, nullable=False)
    date = Column(Date, index=True, nullable=False)

    expiry = Column(Date, index=True, nullable=False)
    strike = Column(Float, index=True, nullable=False)
    option_type = Column(String(2), nullable=False)  # 'CE' or 'PE'

    ltp = Column(Float, nullable=True)   # last traded price
    iv = Column(Float, nullable=True)    # implied volatility
    oi = Column(Float, nullable=True)    # open interest
    volume = Column(Float, nullable=True)

    stock = relationship("Stock", back_populates="options")

    __table_args__ = (
        Index("ix_option_chain_symbol_date_expiry", "symbol", "date", "expiry"),
    )


class News(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), ForeignKey("stocks.symbol"), index=True, nullable=False)

    published_at = Column(DateTime, index=True, nullable=False)
    source = Column(String(128), nullable=True)
    headline = Column(String(512), nullable=False)
    snippet = Column(String(1024), nullable=True)
    url = Column(String(1024), nullable=True)

    stock = relationship("Stock")

    __table_args__ = (
        Index("ix_news_symbol_published_at", "symbol", "published_at"),
    )


class NewsImpact(Base):
    __tablename__ = "news_impact"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), ForeignKey("stocks.symbol"), index=True, nullable=False)
    date = Column(Date, index=True, nullable=False)

    # e.g. strongly_positive, mildly_positive, neutral, mildly_negative, strongly_negative
    sentiment = Column(String(32), nullable=False)

    # e.g. low, medium, high
    impact = Column(String(16), nullable=False)

    # list of event types, we’ll store as JSON array of strings
    event_types = Column(JSON, nullable=True)

    summary = Column(String(1024), nullable=True)      # short LLM summary
    explanation = Column(String(2048), nullable=True)  # LLM explanation
    raw_json = Column(JSON, nullable=True)             # full LLM response if you want

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_news_impact_symbol_date"),
    )


class DailyCandidate(Base):
    __tablename__ = "daily_candidates"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), ForeignKey("stocks.symbol"), index=True, nullable=False)
    date = Column(Date, index=True, nullable=False)

    score = Column(Float, nullable=False)        # combined numeric score
    bias = Column(String(16), nullable=False)    # 'bull', 'bear', 'unclear'

    # store all computed features (gap%, iv%, oi changes, etc.) as JSON
    metadata_json = Column(JSON, nullable=True)

    is_active = Column(Boolean, default=True)  # for later if you want

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_daily_candidates_symbol_date"),
        Index("ix_daily_candidates_date_score", "date", "score"),
    )
