from pydantic import Field

from .common import ContractModel
from .source import SourceReference


class PersonaResult(ContractModel):
    persona: str | None = Field(default=None, max_length=100)
    rationale: str | None = Field(default=None, max_length=2_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_references: list[SourceReference] = Field(default_factory=list, max_length=50)


class Plan(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    steps: list[str] = Field(default_factory=list, max_length=30)


class PlansResult(ContractModel):
    plans: list[Plan] = Field(default_factory=list, max_length=10)
    disclaimer: str | None = Field(default=None, max_length=1_000)
    source_references: list[SourceReference] = Field(default_factory=list, max_length=50)
