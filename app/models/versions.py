from __future__ import annotations
from typing import Literal
from pydantic import BaseModel
from app.models.base import ExtensionBase, Links, Relationship

class VersionAttributes(BaseModel):
    name: str
    displayName: str
    createTime: str
    createUserId: str
    createUserName: str
    lastModifiedTime: str
    lastModifiedUserId: str
    lastModifiedUserName: str
    versionNumber: int
    storageSize: int | None = None
    fileType: str
    extension: ExtensionBase

class Version(BaseModel):
    type: Literal["versions"]
    id: str
    attributes: VersionAttributes
    links: Links | None = None
    relationships: dict[str, Relationship] | None = None
