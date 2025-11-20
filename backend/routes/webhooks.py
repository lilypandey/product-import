from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import requests

from backend.models import Webhook
from backend.database import get_db
from backend.schemas import WebhookCreate, WebhookOut

router = APIRouter(tags=["Webhooks"])

@router.get("/webhooks", response_model=list[WebhookOut])
def list_webhooks(db: Session = Depends(get_db)):
    return db.query(Webhook).all()


@router.post("/webhooks", response_model=WebhookOut)
def create_webhook(data: WebhookCreate, db: Session = Depends(get_db)):
    existing = db.query(Webhook).filter(Webhook.url == data.url).first()
    if existing:
        raise HTTPException(status_code=400, detail="Webhook already exists")

    wh = Webhook(url=data.url, event=data.event)
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(webhook_id: int, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    db.delete(wh)
    db.commit()
    return {"deleted": True}


@router.post("/webhooks/test/{webhook_id}")
def test_webhook(webhook_id: int, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    payload = {"event": wh.event, "message": "Test event."}
    try:
        r = requests.post(wh.url, json=payload, timeout=5)
        return {"status": "sent", "response_code": r.status_code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/webhooks/ui", response_class=HTMLResponse)
def webhook_ui():
    with open("frontend/webhooks.html") as f:
        return f.read()