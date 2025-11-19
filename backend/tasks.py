import csv
import os
import redis
from backend.database import SessionLocal
from backend.models import Product

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def import_csv_task(filepath: str, task_id: str, *args, **kwargs):

    from backend.main import notify_webhooks
    db = SessionLocal()

    try:
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        total = len(rows)
        processed = 0

        for row in rows:
            sku = row.get("sku") or ""
            name = row.get("name") or ""
            description = row.get("description") or ""

            product = db.query(Product).filter(Product.sku == sku).first()

            if product:
                product.name = name
                product.description = description
            else:
                db.add(Product(sku=sku, name=name, description=description))

            db.commit()

            processed += 1
            progress = int((processed / total) * 100)

            redis_client.publish(f"progress_channel:{task_id}", progress)
            redis_client.set(f"progress:{task_id}", progress)

        notify_webhooks(
            {
                "event": "product.changed",
                "action": "csv_import",
                "count": processed,
            },
            db
        )

    finally:
        db.close()
