from __future__ import annotations
from typing import Literal
from pydantic import BaseModel
from app.models.base import BaseAttributes, Resource, Links, Relationship

class ItemAttributes(BaseAttributes):
    displayName: str
    createTime: str
    createUserId: str
    createUserName: str
    lastModifiedTime: str
    lastModifiedUserId: str
    lastModifiedUserName: str
    lastModifiedTimeRollup: str
    hidden: bool
    reserved: bool | None = None
    reservedTime: str | None = None
    reservedUserId: str | None = None
    reservedUserName: str | None = None

class RelationshipData(BaseModel):
    type: str
    id: str

class RelationshipWithData(Relationship):
    data: RelationshipData

class ItemRelationships(BaseModel):
    tip: RelationshipWithData
    versions: Relationship
    refs: Relationship
    links: Relationship
    parent: RelationshipWithData

class Item(Resource[ItemAttributes]):
    type: Literal["items"] = "items"
    relationships: ItemRelationships


class VersionAttributes(BaseAttributes):
    name: str
    displayName: str
    createTime: str
    createUserId: str
    createUserName: str
    lastModifiedTime: str
    lastModifiedUserId: str
    lastModifiedUserName: str
    versionNumber: int
    mimeType: str | None = None

class VersionLinks(Links):
    webView: dict[str, str] | None = None

class StorageRelationshipMeta(BaseModel):
    link: dict[str, str]

class StorageRelationship(BaseModel):
    meta: StorageRelationshipMeta
    data: RelationshipData

class VersionRelationships(BaseModel):
    item: RelationshipWithData
    refs: Relationship
    links: Relationship
    storage: StorageRelationship

class Version(Resource[VersionAttributes]):
    type: Literal["versions"] = "versions"
    links: VersionLinks | None = None
    relationships: VersionRelationships
