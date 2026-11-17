from enum import StrEnum
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl

LOCAL = ZoneInfo("America/Chicago")


class Kind(StrEnum):
    agenda = "agenda"
    minutes = "minutes"
    notice = "notice"
    attachment = "attachment"


class State(StrEnum):
    proposed = "proposed"
    scheduled = "scheduled"
    discussed = "discussed"
    approved = "approved"
    rejected = "rejected"
    tabled = "tabled"
    unknown = "unknown"


DECISIONS = {State.approved, State.rejected, State.tabled}


class MeetingRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,119}$")
    body: str = Field(min_length=1, max_length=140)
    title: str = Field(min_length=1, max_length=250)
    starts_at: AwareDatetime
    location: str | None = Field(default=None, max_length=300)
    source_url: HttpUrl
    status: str = "scheduled"


class DocumentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=180)
    kind: Kind
    url: HttpUrl
    published_at: AwareDatetime | None = None
    authoritative: bool = False


class DiscoveredMeeting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meeting: MeetingRef
    documents: list[DocumentRef] = Field(default_factory=list)


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    segment_id: str
    quote: str = Field(min_length=4, max_length=1200)


class ModelVote(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    yeas: int = Field(ge=0, le=50)
    nays: int = Field(ge=0, le=50)


class ModelObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    official_id: str
    outcome: State
    evidence: EvidenceRef
    vote: ModelVote | None = None
    confidence: float = Field(ge=0, le=1)


class ModelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    observations: Annotated[list[ModelObservation], Field(max_length=20)]
