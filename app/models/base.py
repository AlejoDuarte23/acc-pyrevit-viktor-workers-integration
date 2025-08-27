from __future__ import annotations
from typing import Any, Generic, TypeVar, Optional
from pydantic import BaseModel, ConfigDict, Field

class ExtensionBase(BaseModel):
    """Common extension payload returned by every APS resource."""
    type: str
    version: str
    schema_ref: dict[str, str] | None = Field(None, alias="schema")
    data: dict[str, Any] = Field(default_factory=dict)


class Links(BaseModel):
    self: dict[str, str] | None = None
    related: None | dict[str, str] = None
    webView: None | dict[str, str] = None


class RelationshipData(BaseModel):
    type: str
    id: str

class Relationship(BaseModel):
    """Minimal JSON API relationship object."""
    links: Optional[Links] = None
    data: Optional[RelationshipData | list[RelationshipData]] = None
    meta: Optional[dict[str, Any]] = None


AttrT = TypeVar("AttrT", bound="BaseAttributes")

class BaseAttributes(BaseModel):
    extension: ExtensionBase

class Resource(BaseModel, Generic[AttrT]):
    """
    Generic JSON API resource.
    Subclasses fix `type` with Literal
    and override `attributes` with a concrete class.
    """
    model_config = ConfigDict(extra="allow")   # for unknown fields
    type: str
    id: str
    attributes: AttrT
    links: Links | None = None
    relationships: dict[str, Relationship] | None = None
