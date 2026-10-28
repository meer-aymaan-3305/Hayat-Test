from datetime import datetime
from uuid import UUID

from pydantic import Field

from .common import ContractModel, new_id, now_utc


class GuestSessionCreate(ContractModel):
    locale: str = Field(default="en", min_length=2, max_length=16)
    client_metadata: dict[str, str] = Field(default_factory=dict)


class GuestSession(GuestSessionCreate):
    id: UUID = Field(default_factory=new_id)
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)
