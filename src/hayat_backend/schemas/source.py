from uuid import UUID

from pydantic import Field, HttpUrl

from .common import ContractModel, new_id


class SourceReference(ContractModel):
    id: UUID = Field(default_factory=new_id)
    title: str = Field(min_length=1, max_length=300)
    uri: HttpUrl | None = None
    document_id: UUID | None = None
    excerpt: str | None = Field(default=None, max_length=2_000)
