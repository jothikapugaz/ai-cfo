import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

import ai_engine
import auth
import models
import schemas
from database import Base, engine, get_db

Base.metadata.create_all(bind=engine)
ai_engine.configure_genai()

app = FastAPI(title="AI Personal CFO & Wealth Advisor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def save_upload_file(user_id: int, file: UploadFile) -> str:
    contents = file.file.read()
    ext = os.path.splitext(file.filename or "")[1] or ".bin"
    user_dir = os.path.join(UPLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(user_dir, filename)
    with open(file_path, "wb") as f:
        f.write(contents)
    return f"/{UPLOAD_DIR}/{user_id}/{filename}"


def receipt_to_out(receipt: models.Receipt, db: Session) -> schemas.ReceiptOut:
    items = (
        db.query(models.LineItem)
        .filter(
            models.LineItem.receipt_id == receipt.receipt_id,
            models.LineItem.user_id == receipt.user_id,
        )
        .all()
    )
    return schemas.ReceiptOut(
        receipt_id=receipt.receipt_id,
        merchant_name=receipt.merchant_name,
        total_amount=receipt.total_amount,
        image_url=receipt.image_url,
        processing_status=receipt.processing_status,
        timestamp=receipt.timestamp,
        line_items=[schemas.LineItemOut.model_validate(i) for i in items],
    )


# Health
@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-cfo"}


# Root serving PWA
@app.get("/")
def serve_frontend():
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "index.html"))


# Auth
@app.post("/auth/register", response_model=schemas.UserOut, status_code=201)
def register(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = models.User(
        email=user_data.email,
        password_hash=auth.get_password_hash(user_data.password),
        primary_language=user_data.primary_language,
        low_literacy_mode=user_data.low_literacy_mode,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=schemas.Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = auth.create_access_token({"sub": user.email})
    return schemas.Token(access_token=token, user=schemas.UserOut.model_validate(user))


@app.get("/auth/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


# Receipts
@app.post("/receipts", response_model=schemas.ReceiptOut, status_code=201)
async def create_receipt(
    file: UploadFile = File(...),
    total_amount: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    image_url = save_upload_file(current_user.user_id, file)

    try:
        extraction = ai_engine.extract_receipt_data(
            image_bytes, file.content_type or "image/jpeg"
        )
    except Exception:
        extraction = {
            "merchant_name": "Unknown Merchant",
            "total_amount": total_amount or 0.0,
            "processing_status": "Incomplete",
            "line_items": [],
        }

    total = Decimal(str(extraction.get("total_amount") or total_amount or 0))
    receipt = models.Receipt(
        user_id=current_user.user_id,
        merchant_name=extraction.get("merchant_name", "Unknown Merchant"),
        total_amount=total,
        image_url=image_url,
        processing_status=extraction.get("processing_status", "Incomplete"),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)

    for item in extraction.get("line_items", []):
        li = models.LineItem(
            receipt_id=receipt.receipt_id,
            user_id=current_user.user_id,
            product_name=str(item.get("product_name", "Unnamed")),
            quantity=Decimal(str(item.get("quantity", 1))),
            unit_price=Decimal(str(item.get("unit_price", 0))),
            category=str(item.get("category", "Uncategorized")),
        )
        db.add(li)

    if extraction.get("line_items"):
        receipt.processing_status = "Success"
    else:
        receipt.processing_status = "Incomplete"

    db.commit()
    db.refresh(receipt)
    return receipt_to_out(receipt, db)


@app.get("/receipts", response_model=List[schemas.ReceiptOut])
def list_receipts(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    receipts = (
        db.query(models.Receipt)
        .filter(models.Receipt.user_id == current_user.user_id)
        .order_by(models.Receipt.timestamp.desc())
        .all()
    )
    return [receipt_to_out(r, db) for r in receipts]


@app.get("/receipts/{receipt_id}", response_model=schemas.ReceiptOut)
def get_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    receipt = (
        db.query(models.Receipt)
        .filter(
            models.Receipt.receipt_id == receipt_id,
            models.Receipt.user_id == current_user.user_id,
        )
        .first()
    )
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return receipt_to_out(receipt, db)


@app.delete("/receipts/{receipt_id}", status_code=204)
def delete_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    receipt = (
        db.query(models.Receipt)
        .filter(
            models.Receipt.receipt_id == receipt_id,
            models.Receipt.user_id == current_user.user_id,
        )
        .first()
    )
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    db.delete(receipt)
    db.commit()


# Income
@app.post("/incomes", response_model=schemas.IncomeOut, status_code=201)
def create_income(
    income_data: schemas.IncomeCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    income = models.Income(
        user_id=current_user.user_id,
        amount=income_data.amount,
        source=income_data.source,
        timestamp=income_data.timestamp or datetime.utcnow(),
    )
    db.add(income)
    db.commit()
    db.refresh(income)
    return income


@app.get("/incomes", response_model=List[schemas.IncomeOut])
def list_incomes(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return (
        db.query(models.Income)
        .filter(models.Income.user_id == current_user.user_id)
        .order_by(models.Income.timestamp.desc())
        .all()
    )


# Voice
@app.post("/voice", response_model=schemas.VoiceLogOut)
async def create_voice(
    file: UploadFile = File(...),
    receipt_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    save_upload_file(current_user.user_id, file)

    try:
        transcription = ai_engine.transcribe_audio(
            audio_bytes,
            file.content_type or "audio/webm",
            current_user.primary_language,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice transcription failed: {str(e)}")

    voice_log = models.VoiceLog(
        user_id=current_user.user_id,
        transcription=transcription,
    )
    db.add(voice_log)
    db.commit()
    db.refresh(voice_log)

    if receipt_id:
        receipt = (
            db.query(models.Receipt)
            .filter(
                models.Receipt.receipt_id == receipt_id,
                models.Receipt.user_id == current_user.user_id,
            )
            .first()
        )
        if receipt and receipt.processing_status == "Incomplete" and receipt.total_amount > 0:
            try:
                items = ai_engine.allocate_total_from_voice(
                    transcription,
                    float(receipt.total_amount),
                    current_user.primary_language,
                )
                for item in items:
                    li = models.LineItem(
                        receipt_id=receipt.receipt_id,
                        user_id=current_user.user_id,
                        product_name=item["product_name"],
                        quantity=Decimal(str(item.get("quantity", 1))),
                        unit_price=Decimal(str(item.get("unit_price", 0))),
                        category=item.get("category", "Uncategorized"),
                    )
                    db.add(li)
                receipt.processing_status = "Success"
                db.commit()
            except Exception:
                pass

    return voice_log


# Insights
@app.get("/insights", response_model=List[schemas.InsightOut])
def list_insights(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return (
        db.query(models.StrategicInsight)
        .filter(models.StrategicInsight.user_id == current_user.user_id)
        .order_by(models.StrategicInsight.timestamp.desc())
        .all()
    )


@app.post("/insights/generate", response_model=List[schemas.InsightOut])
def generate_insights(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    new_insights = []

    # Price-gouging: same product at same merchant, historical unit price comparison
    rows = (
        db.query(models.LineItem, models.Receipt)
        .join(models.Receipt, models.LineItem.receipt_id == models.Receipt.receipt_id)
        .filter(models.LineItem.user_id == current_user.user_id)
        .order_by(models.Receipt.timestamp.asc())
        .all()
    )

    groups = {}
    for li, receipt in rows:
        key = (receipt.merchant_name or "Unknown Merchant", li.product_name)
        groups.setdefault(key, []).append((receipt.timestamp, float(li.unit_price)))

    for (merchant, product), prices in groups.items():
        if len(prices) >= 2:
            prev_ts, prev_price = prices[-2]
            latest_ts, latest_price = prices[-1]
            if prev_price > 0 and latest_price > prev_price:
                pct = (latest_price - prev_price) / prev_price * 100
                text = f"{merchant} raised {product} price by {pct:.1f}% since your last visit."
                new_insights.append((text, "Price Hike"))

    # Anti-waste: recurring identical product charges
    recurring = (
        db.query(
            models.LineItem.product_name,
            func.count(models.LineItem.item_id).label("cnt"),
            func.avg(models.LineItem.unit_price).label("avg_price"),
        )
        .filter(models.LineItem.user_id == current_user.user_id)
        .group_by(models.LineItem.product_name)
        .having(func.count(models.LineItem.item_id) >= 2)
        .all()
    )
    for product_name, cnt, avg_price in recurring:
        text = (
            f"Recurring charge detected: {product_name} appears {cnt} times with average "
            f"amount {float(avg_price):.2f}. Review if this is a hidden subscription or waste."
        )
        new_insights.append((text, "Hidden Expense"))

    for text, category in new_insights:
        exists = (
            db.query(models.StrategicInsight)
            .filter(
                models.StrategicInsight.user_id == current_user.user_id,
                models.StrategicInsight.insight_text == text,
            )
            .first()
        )
        if not exists:
            db.add(
                models.StrategicInsight(
                    user_id=current_user.user_id,
                    insight_text=text,
                    category=category,
                )
            )

    db.commit()
    return (
        db.query(models.StrategicInsight)
        .filter(models.StrategicInsight.user_id == current_user.user_id)
        .order_by(models.StrategicInsight.timestamp.desc())
        .all()
    )


# Admin Dashboard
@app.get("/admin/dashboard", response_model=schemas.AdminMetrics)
def admin_dashboard(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.get_current_admin_user),
):
    total_users = db.query(models.User).count()
    today = datetime.utcnow().date()

    daily_receipt_users = (
        db.query(func.count(distinct(models.Receipt.user_id)))
        .filter(models.Receipt.timestamp >= today)
        .scalar()
        or 0
    )
    daily_income_users = (
        db.query(func.count(distinct(models.Income.user_id)))
        .filter(models.Income.timestamp >= today)
        .scalar()
        or 0
    )
    daily_voice_users = (
        db.query(func.count(distinct(models.VoiceLog.user_id)))
        .filter(models.VoiceLog.timestamp >= today)
        .scalar()
        or 0
    )
    daily_active_users = daily_receipt_users + daily_income_users + daily_voice_users

    total_documents = db.query(models.Receipt).count()
    total_audio = db.query(models.VoiceLog).count()

    now = datetime.utcnow()
    start_recent = now - timedelta(days=30)
    start_previous = now - timedelta(days=60)

    def category_avg(start, end):
        rows = (
            db.query(
                models.LineItem.category,
                func.avg(models.LineItem.unit_price),
            )
            .filter(models.LineItem.created_at >= start, models.LineItem.created_at < end)
            .group_by(models.LineItem.category)
            .all()
        )
        return {cat: float(avg) for cat, avg in rows}

    recent_avg = category_avg(start_recent, now)
    previous_avg = category_avg(start_previous, start_recent)

    inflation = []
    for category, avg in recent_avg.items():
        if category in previous_avg and previous_avg[category] > 0:
            pct = (avg - previous_avg[category]) / previous_avg[category] * 100
            inflation.append(
                {
                    "category": category,
                    "inflation_pct": round(pct, 2),
                    "recent_avg_price": round(avg, 2),
                    "previous_avg_price": round(previous_avg[category], 2),
                }
            )

    inflation.sort(key=lambda x: x["inflation_pct"], reverse=True)
    top5 = inflation[:5]

    return schemas.AdminMetrics(
        total_users=total_users,
        daily_active_users=daily_active_users,
        total_documents=total_documents,
        total_audio=total_audio,
        top_inflating_categories=top5,
)
