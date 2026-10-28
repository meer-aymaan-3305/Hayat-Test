from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def new_id() -> UUID:
    return uuid4()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


NonEmptyText = Field(min_length=1, max_length=8_000)
