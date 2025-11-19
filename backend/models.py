from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, func, Index, DateTime
from backend.database import Base

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, nullable=False)
    name = Column(String)
    description = Column(String)
    active = Column(Boolean, default=True)

    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, onupdate=func.now())

    __table_args__ = (
        Index("ix_products_sku_lower", func.lower(sku), unique=True),
    )


class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False, unique=True)
    event = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
