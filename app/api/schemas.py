"""Pydantic request models for the REST /v1 surface.

`kind`, `scope`, and `sensitivity` use the same Literals as the MCP tools so
both surfaces validate identically.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import AccessLevel, LinkAccess, MemoryKind, Scope, Sensitivity


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""


class ShareRequest(BaseModel):
    email: str = Field(..., min_length=3)
    access: AccessLevel = "edit"


class AccessRequest(BaseModel):
    access: AccessLevel


class LinkAccessRequest(BaseModel):
    """`manage` is absent from LinkAccess by design — a link cannot re-share."""

    access: LinkAccess


class AddMemberRequest(BaseModel):
    email: str
    role: str = "member"


class CreateSessionRequest(BaseModel):
    client_session_ref: str = Field(..., min_length=1)


class SyncRequest(BaseModel):
    task: str = Field(..., min_length=1)
    session_ref: str = Field(default="default")
    local_context_delta: str = ""
    known_revision: int | None = None
    budget_tokens: int = Field(default=3000, ge=500, le=20000)
    delta_scope: Scope = "shared"


class RememberRequest(BaseModel):
    kind: MemoryKind = "finding"
    summary: str = Field(..., min_length=1)
    details: str = ""
    tags: list[str] = Field(default_factory=list)
    importance: float = Field(default=0.6, ge=0.0, le=1.0)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    sensitivity: Sensitivity = "internal"
    supersedes: list[str] = Field(default_factory=list)
    contradicts: list[str] = Field(default_factory=list)
    session_ref: str | None = None
