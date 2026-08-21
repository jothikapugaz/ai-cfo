import json
import logging
import os
import tempfile
from decimal import Decimal
from typing import Any, Dict, List

import google.generativeai as genai

logger = logging.getLogger(__name__)


def configure_genai() -> bool:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set. AI features will fail unless configured.")
        return False
    genai.configure(api_key=api_key)
    return True


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    return raw


def extract_receipt_data(image_bytes: bytes, mime_type: str = "image/jpeg") -> Dict[str, Any]:
    if not os.getenv("GEMINI_API_KEY"):
        raise ValueError("GEMINI_API_KEY is not configured")

    prompt = """
You are a financial data extraction AI. Extract data from the receipt image.
Return strict JSON with the following keys:
{
  "merchant_name": string,
  "total_amount": number,
  "processing_status": "Success" or "Incomplete",
  "line_items": [
    {"product_name": string, "quantity": number, "unit_price": number, "category": string}
  ]
}
If item names or unit prices cannot be read clearly, set line_items to [] and processing_status to "Incomplete".
"""

    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        generation_config={"response_mime_type": "application/json", "temperature": 0.1},
    )
    response = model.generate_content(
        [prompt, {"mime_type": mime_type, "data": image_bytes}]
    )
    raw = _clean_json(response.text)
    data = json.loads(raw)

    data.setdefault("merchant_name", "Unknown Merchant")
    data.setdefault("total_amount", 0.0)
    data.setdefault("line_items", [])
    data.setdefault("processing_status", "Success" if data["line_items"] else "Incomplete")
    return data


def transcribe_audio(audio_bytes: bytes, mime_type: str, language: str = "en") -> str:
    if not os.getenv("GEMINI_API_KEY"):
        raise ValueError("GEMINI_API_KEY is not configured")

    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"Transcribe the following spoken audio in {language}. Return only the transcription text with no extra commentary."

    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as f:
        f.write(audio_bytes)
        temp_path = f.name

    try:
        uploaded_audio = genai.upload_file(temp_path, mime_type=mime_type)
        response = model.generate_content([prompt, uploaded_audio])
        return response.text.strip()
    finally:
        os.unlink(temp_path)


def allocate_total_from_voice(
    transcription: str,
    total_amount: float,
    language: str = "en",
) -> List[Dict[str, Any]]:
    if not os.getenv("GEMINI_API_KEY"):
        raise ValueError("GEMINI_API_KEY is not configured")

    prompt = f"""
You are an AI CFO. A user described what they purchased by voice: "{transcription}".
Total receipt amount is {total_amount}.
Return a JSON object with key "items": an array of objects with keys:
"product_name", "quantity", "unit_price", "category".
If unit prices are not specified in the voice note, allocate the total amount equally among the named items.
Strictly return JSON.
"""

    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        generation_config={"response_mime_type": "application/json", "temperature": 0.1},
    )
    response = model.generate_content(prompt)
    raw = _clean_json(response.text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}

    items = data.get("items", [])
    if not items:
        names = [
            s.strip()
            for s in transcription.replace(" and ", ",").replace(",", "|").split("|")
            if s.strip()
        ]
        if not names:
            names = ["Unspecified item"]
        share = Decimal(str(total_amount)) / Decimal(len(names))
        items = [
            {"product_name": name, "quantity": 1, "unit_price": float(share), "category": "Uncategorized"}
            for name in names
        ]

    normalized = []
    for it in items:
        normalized.append(
            {
                "product_name": str(it.get("product_name", "Item")),
                "quantity": float(it.get("quantity", 1) or 1),
                "unit_price": float(it.get("unit_price", 0) or 0),
                "category": str(it.get("category", "Uncategorized")),
            }
        )
    return normalized
