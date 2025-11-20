from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
import asyncio

from backend.models import Product
from backend.database import get_db
from backend.schemas import ProductCreate, ProductUpdate, ProductOut, BulkDeleteRequest
from backend.utils import notify_webhooks
from backend.config import redis_client
from sse_starlette.sse import EventSourceResponse

router = APIRouter(tags=["Products"])

@router.get("/products", response_model=dict)
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

@router.post("/products", response_model=ProductOut)
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

@router.put("/products/{product_id}", response_model=ProductOut)
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


@router.delete("/products/bulk", response_model=dict)
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

@router.delete("/products/{product_id}")
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


@router.get("/products/ui", response_class=HTMLResponse)
def products_ui():
    with open("frontend/products.html", "r", encoding="utf-8") as f:
        return f.read()

@router.get("/products/events")
async def products_events():
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