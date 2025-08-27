from __future__ import annotations
from typing import Any, Literal, Annotated
from pydantic import BaseModel, Field
from app.models.folders import Folder
from app.models.base import Links, Relationship


class ItemAttributes(BaseModel):
    displayName: str
    createTime: str
    createUserId: str
    createUserName: str
    lastModifiedTime: str
    lastModifiedUserId: str
    lastModifiedUserName: str
    hidden: bool
    extension: dict[str, Any]
    lastModifiedTimeRollup: str | None = None


class Item(BaseModel):
    type: Literal["items"]
    id: str
    attributes: ItemAttributes
    links: None | Links = None
    relationships: dict[str, Relationship] | None = None


class ContentsLinks(BaseModel):
    self: dict[str, str]
    first: dict[str, str] | None = None
    prev: dict[str, str] | None = None
    next: dict[str, str] | None = None


class FolderContentsList(BaseModel):
    jsonapi: dict[str, str]
    links: ContentsLinks
    data: list[Annotated[Folder | Item, Field(discriminator="type")]]
