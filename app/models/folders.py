from typing import Any, Literal
from pydantic import BaseModel, Field

class FolderExtension(BaseModel):
    type: str
    version: str
    schema_: dict[str, str] | None = Field(None, alias="schema")
    data: dict[str, Any] = Field(default_factory=dict)

class FolderAttributes(BaseModel):
    name: str
    displayName: str
    createTime: str
    createUserId: str
    createUserName: str
    lastModifiedTime: str
    lastModifiedUserId: str
    lastModifiedUserName: str
    lastModifiedTimeRollup: str
    objectCount: int
    hidden: bool
    extension: FolderExtension
    path: str | None = None

class FolderLinks(BaseModel):
    self: dict[str, str]
    webView: dict[str, str] | None = None

class FolderRelationshipLinks(BaseModel):
    self: None | dict[str, str] = None
    related: None | dict[str, str] = None

class FolderRelationshipData(BaseModel):
    type: str
    id: str

class FolderRelationship(BaseModel):
    links: None | FolderRelationshipLinks = None
    data: None | FolderRelationshipData = None

class FolderRelationships(BaseModel):
    parent: None | FolderRelationship = None
    refs: None | FolderRelationship = None
    links: None | FolderRelationship = None
    contents: None | FolderRelationship = None

class Folder(BaseModel):
    type: Literal["folders"]
    id: str
    attributes: FolderAttributes
    links: FolderLinks
    relationships: None | FolderRelationships = None

class FoldersList(BaseModel):
    jsonapi: dict[str, str]
    links: dict[str, dict[str, str]]
    data: list[Folder]
