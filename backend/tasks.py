import os
import csv
import redis
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from backend.database import SessionLocal
from backend.models import Product
from backend.celery_app import celery_app

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


@celery_app.task(bind=True)
def import_csv_task(self, filepath, task_id):
    session = SessionLocal()

    with open(filepath, encoding="utf-8") as f:
        total = sum(1 for _ in f) - 1

    processed = 0
    batch = []

    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            processed += 1

            sku = row.get("sku", "").strip()
            name = row.get("name", "").strip()
            desc = row.get("description", "").strip()

            existing = session.query(Product).filter(
                func.lower(Product.sku) == sku.lower()
            ).first()

            if existing:
                existing.name = name or existing.name
                existing.description = desc or existing.description
            else:
                batch.append(Product(
                    sku=sku,
                    name=name,
                    description=desc,
                    active=True
                ))

            if len(batch) >= 500:
                try:
                    session.bulk_save_objects(batch)
                    session.commit()
                except IntegrityError:
                    session.rollback()
                batch = []

            percent = max(1, int((processed / total) * 100))
            redis_client.set(f"progress:{task_id}", percent)
            redis_client.publish(f"progress_channel:{task_id}", percent)

    if batch:
        try:
            session.bulk_save_objects(batch)
            session.commit()
        except IntegrityError:
            session.rollback()

    redis_client.set(f"progress:{task_id}", 100)
    redis_client.publish(f"progress_channel:{task_id}", 100)

    return {"status": "completed"}
