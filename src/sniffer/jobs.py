from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sniffer.settings import NAME_PATTERN


class SearchJob(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1] = 1
    job_id: str = Field(pattern=NAME_PATTERN)
    action: Literal["search"] = "search"
    keyword: str = Field(min_length=1, max_length=200)
    scroll_count: int = Field(default=5, ge=0, le=100)
    scroll_pause_ms: int = Field(default=1500, ge=100, le=30000)


class InvalidJob(ValueError):
    """Payload must not be retried."""


class JobConflict(InvalidJob):
    """A previously completed job ID was reused for different work."""
