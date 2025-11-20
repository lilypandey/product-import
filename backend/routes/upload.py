import os
import uuid
import asyncio

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.tasks import import_csv_task
from backend.config import UPLOAD_DIR, redis_client

router = APIRouter(tags=["Upload"])

@router.get("/", response_class=HTMLResponse)
def home():
    with open("frontend/upload.html", "r", encoding="utf-8") as f:
        return f.read()


@router.post("/upload")
async def upload_csv(
    file: UploadFile = File(...),
    background: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    task_id = str(uuid.uuid4())
    filename = f"{task_id}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    background.add_task(import_csv_task, filepath, task_id, db, redis_client)

    return {"task_id": task_id}

@router.get("/progress/{task_id}")
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