from fastapi import FastAPI
from backend.database import Base, engine
from backend.routes.upload import router as upload_router
from backend.routes.products import router as products_router
from backend.routes.webhooks import router as webhooks_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Product Importer")

app.include_router(upload_router)
app.include_router(products_router)
app.include_router(webhooks_router)

