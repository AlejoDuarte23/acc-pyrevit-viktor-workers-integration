from app.models.base import BaseAttributes, Links, Relationship, Resource
from typing import Literal, Any
from pydantic import BaseModel

class ProjectAttributes(BaseAttributes):
    name: str
    scopes: list[str]
    # extension is inherited from BaseAttributes

class ProjectLinks(Links):
    webView: dict[str, str] | None = None

class RelationshipData(BaseModel):
    type: str
    id: str

class RelationshipWithData(BaseModel):
    data: RelationshipData
    meta: dict[str, Any] | None = None
    links: Links | None = None

class ProjectRelationships(BaseModel):
    hub: RelationshipWithData
    rootFolder: RelationshipWithData
    topFolders: Relationship
    # Optionally add other relationships if needed:
    issues: RelationshipWithData | None = None
    submittals: RelationshipWithData | None = None
    rfis: RelationshipWithData | None = None
    markups: RelationshipWithData | None = None
    checklists: RelationshipWithData | None = None
    cost: RelationshipWithData | None = None
    locations: RelationshipWithData | None = None

class Project(Resource[ProjectAttributes]):
    type: Literal["projects"] = "projects"
    links: ProjectLinks | None = None
    relationships: ProjectRelationships

class ProjectsCollectionLinks(BaseModel):
    self: dict[str, str]
    first: dict[str, str] | None = None
    prev: dict[str, str] | None = None
    next: dict[str, str] | None = None

class ProjectsList(BaseModel):
    jsonapi: dict[str, str]
    links: ProjectsCollectionLinks
    data: list[Project]
