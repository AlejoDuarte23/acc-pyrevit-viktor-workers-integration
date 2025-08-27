from app.models.base import BaseAttributes, Links, Relationship, Resource
from typing import Literal, Optional, Any
from pydantic import BaseModel

class HubAttributes(BaseAttributes):
    name: str
    region: str | None = None

class HubRelationships(BaseModel):
    projects: Relationship


class Hub(Resource[HubAttributes]):
    type: Literal["hubs"] = "hubs" 
    relationships: HubRelationships

class HubsList(BaseModel):
    jsonapi: dict[str, Any]
    links: Links
    data: list[Hub]
    meta: Optional[dict[str, Any]] = None