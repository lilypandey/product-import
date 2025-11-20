import requests
from backend.database import SessionLocal
from backend.models import Webhook

def notify_webhooks(payload: dict, db=None):
    if db is None:
        db = SessionLocal()

    webhooks = db.query(Webhook).all()

    for wh in webhooks:
        try:
            requests.post(wh.url, json=payload, timeout=5)
        except Exception:
            continue
