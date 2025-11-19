from typing import List, Optional
from pydantic import BaseModel, ConfigDict

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

class BulkDeleteRequest(BaseModel):
    ids: List[int]

class WebhookCreate(BaseModel):
    url: str
    event: str = "product.changed"


class WebhookOut(BaseModel):
    id: int
    url: str
    event: str

    model_config = ConfigDict(from_attributes=True)