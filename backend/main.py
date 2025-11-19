import os
import uuid
import asyncio
import redis
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import engine, Base, get_db
from backend.models import Product
from backend.tasks import import_csv_task
from backend.models import Webhook
from backend.database import SessionLocal

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI()

Base.metadata.create_all(bind=engine)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
def home():
    with open("frontend/upload.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/upload")
async def upload_csv(file: UploadFile = File(...)):
    task_id = str(uuid.uuid4())
    filename = f"{task_id}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    import_csv_task.delay(filepath, task_id)
    return {"task_id": task_id}

@app.get("/progress/{task_id}")
async def progress_event_stream(task_id: str):
    channel = f"progress_channel:{task_id}"

    loop = asyncio.get_event_loop()
    pubsub = redis_client.pubsub()
    pubsub.subscribe(channel)

    async def event_generator():
        try:
            last = redis_client.get(f"progress:{task_id}")
            if last is not None:
                yield {"data": str(last)}

            while True:
                msg = await loop.run_in_executor(None, pubsub.get_message, 1)
                if msg is None:
                    await asyncio.sleep(0.1)
                    continue
                if msg.get("type") == "message":
                    data = msg.get("data")
                    yield {"data": str(data)}
        finally:
            try:
                pubsub.close()
            except Exception:
                pass

    return EventSourceResponse(event_generator())

class ProductCreate(BaseModel):
    sku: str
    name: str
    description: str
    active: bool = True

class ProductUpdate(BaseModel):
    name: str
    description: str
    active: bool

class ProductOut(BaseModel):
    id: int
    sku: str
    name: Optional[str]
    description: Optional[str]
    active: bool

    model_config = ConfigDict(from_attributes=True)

@app.get("/products", response_model=dict)
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    sku: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Product)
    if sku:
        query = query.filter(func.lower(Product.sku).like(f"%{sku.lower()}%"))
    if name:
        query = query.filter(func.lower(Product.name).like(f"%{name.lower()}%"))
    if description:
        query = query.filter(func.lower(Product.description).like(f"%{description.lower()}%"))
    if active is not None:
        query = query.filter(Product.active == active)

    total = query.count()
    pages = (total + page_size - 1) // page_size

    items = (
        query
        .order_by(Product.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [ProductOut.from_orm(p).dict() for p in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }

@app.post("/products", response_model=ProductOut)
def create_product(data: ProductCreate, db: Session = Depends(get_db)):
    existing = db.query(Product).filter(func.lower(Product.sku) == data.sku.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="SKU already exists")

    p = Product(
        sku=data.sku,
        name=data.name,
        description=data.description,
        active=data.active,
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    redis_client.publish("products_events", "changed")
    notify_webhooks({
        "event": "product.changed",
        "action": "created",
        "product_id": p.id
    }, db)
    return p

@app.put("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, data: ProductUpdate, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    p.name = data.name
    p.description = data.description
    p.active = data.active

    db.add(p)
    db.commit()
    db.refresh(p)

    redis_client.publish("products_events", "changed")
    notify_webhooks({
        "event": "product.changed",
        "action": "updated",
        "product_id": product_id
    }, db)
    return p

class BulkDeleteRequest(BaseModel):
    ids: List[int]

@app.delete("/products/bulk", response_model=dict)
def bulk_delete(data: BulkDeleteRequest, db: Session = Depends(get_db)):
    count = (
        db.query(Product)
        .filter(Product.id.in_(data.ids))
        .delete(synchronize_session=False)
    )
    db.commit()

    redis_client.publish("products_events", "changed")
    notify_webhooks({
        "event": "product.changed",
        "action": "bulk_delete",
        "count": count,
        "ids": data.ids
    }, db)

    return {"deleted": count}

@app.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    db.delete(p)
    db.commit()
    redis_client.publish("products_events", "changed")
    notify_webhooks({
        "event": "product.changed",
        "action": "deleted",
        "product_id": product_id
    }, db)
    return {"status": "deleted"}


@app.get("/products/ui", response_class=HTMLResponse)
def products_ui():
    with open("frontend/products.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/products/events")
async def products_events():
    """
    SSE endpoint that notifies the UI whenever products change.
    Celery task + CRUD endpoints publish to Redis channel 'products_events'.
    """
    loop = asyncio.get_event_loop()
    pubsub = redis_client.pubsub()
    pubsub.subscribe("products_events")

    async def event_generator():
        try:
            while True:
                msg = await loop.run_in_executor(None, pubsub.get_message, 1)
                if msg is None:
                    await asyncio.sleep(0.1)
                    continue
                if msg.get("type") == "message":
                    yield {"data": "changed"}
        finally:
            try:
                pubsub.close()
            except Exception:
                pass

    return EventSourceResponse(event_generator())

class WebhookCreate(BaseModel):
    url: str
    event: str = "product.changed"


class WebhookOut(BaseModel):
    id: int
    url: str
    event: str

    model_config = ConfigDict(from_attributes=True)


import requests

@app.get("/webhooks", response_model=list[WebhookOut])
def list_webhooks(db: Session = Depends(get_db)):
    return db.query(Webhook).all()


@app.post("/webhooks", response_model=WebhookOut)
def create_webhook(data: WebhookCreate, db: Session = Depends(get_db)):
    existing = db.query(Webhook).filter(Webhook.url == data.url).first()
    if existing:
        raise HTTPException(status_code=400, detail="Webhook already exists")

    wh = Webhook(url=data.url, event=data.event)
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


@app.delete("/webhooks/{webhook_id}")
def delete_webhook(webhook_id: int, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    db.delete(wh)
    db.commit()
    return {"deleted": True}


@app.post("/webhooks/test/{webhook_id}")
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

@app.get("/webhooks/ui", response_class=HTMLResponse)
def webhook_ui():
    with open("frontend/webhooks.html") as f:
        return f.read()
    

def notify_webhooks(payload: dict, db: Session = None):
    if db is None:
        db = SessionLocal()

    webhooks = db.query(Webhook).all()

    for wh in webhooks:
        try:
            requests.post(wh.url, json=payload, timeout=5)
        except Exception:
            continue

