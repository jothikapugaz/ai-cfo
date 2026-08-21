from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import Optional, List, Any, Dict
from datetime import datetime
from decimal import Decimal


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    primary_language: str = Field(default="en", max_length=10)
    low_literacy_mode: bool = False


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: EmailStr
    primary_language: str
    low_literacy_mode: bool
    is_admin: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class LineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: int
    receipt_id: int
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    category: str


class ReceiptCreate(BaseModel):
    total_amount: Optional[Decimal] = None
    merchant_name: Optional[str] = None


class ReceiptOut(BaseModel):
    receipt_id: int
    merchant_name: Optional[str]
    total_amount: Decimal
    image_url: Optional[str]
    processing_status: str
    timestamp: datetime
    line_items: List[LineItemOut] = []


class IncomeCreate(BaseModel):
    amount: Decimal
    source: str = Field(default="salary", max_length=50)
    timestamp: Optional[datetime] = None


class IncomeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    income_id: int
    amount: Decimal
    source: str
    timestamp: datetime


class VoiceLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    log_id: int
    transcription: str
    timestamp: datetime


class InsightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    insight_id: int
    insight_text: str
    category: str
    timestamp: datetime


class AdminMetrics(BaseModel):
    total_users: int
    daily_active_users: int
    total_documents: int
    total_audio: int
    top_inflating_categories: List[Dict[str, Any]]
