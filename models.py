from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    Numeric,
    DateTime,
    ForeignKey,
    Text,
    func,
)
from database import Base


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    primary_language = Column(String(10), default="en", nullable=False)
    low_literacy_mode = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Receipt(Base):
    __tablename__ = "receipts"

    receipt_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merchant_name = Column(String(255), nullable=True)
    total_amount = Column(Numeric(12, 2), nullable=False)
    image_url = Column(String(500), nullable=True)
    processing_status = Column(String(20), default="Incomplete", nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class LineItem(Base):
    __tablename__ = "line_items"

    item_id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(
        Integer,
        ForeignKey("receipts.receipt_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_name = Column(String(255), nullable=False)
    quantity = Column(Numeric(12, 3), default=1, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    category = Column(String(100), default="Uncategorized", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Income(Base):
    __tablename__ = "incomes"

    income_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount = Column(Numeric(12, 2), nullable=False)
    source = Column(String(50), nullable=False)  # salary, daily wages, cash
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class VoiceLog(Base):
    __tablename__ = "voice_logs"

    log_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    transcription = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class StrategicInsight(Base):
    __tablename__ = "strategic_insights"

    insight_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    insight_text = Column(Text, nullable=False)
    category = Column(String(50), nullable=False)  # Price Hike, Hidden Expense
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
