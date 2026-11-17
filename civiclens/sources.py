"""Adapters for public, unauthenticated municipal records."""

from dataclasses import dataclass
from datetime import date, datetime, time
import re
from typing import Protocol

import httpx

from civiclens.types import LOCAL, DiscoveredMeeting, DocumentRef, Kind, MeetingRef

CIVIC_HOST = "hattiesburgms.api.civicclerk.com"
LEGISTAR_HOST = "hattiesburgms.legistar.com"
PUBLIC_HOSTS = {CIVIC_HOST, LEGISTAR_HOST, "www.hattiesburgms.com", "hattiesburgms.com"}
USER_AGENT = "CivicLens/0.1 (public meeting records)"
TYPE_MAP = {"agenda": Kind.agenda, "minutes": Kind.minutes, "public notice": Kind.notice,
            "notice": Kind.notice}


class Source(Protocol):
    def discover(self, start: date, end: date) -> list[DiscoveredMeeting]: ...


def public_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=45, follow_redirects=False)


@dataclass
class HattiesburgCivicClerk:
    client: httpx.Client

    def discover(self, start: date, end: date) -> list[DiscoveredMeeting]:
        """Read a half-open local-date window using the public OData feed."""
        if end <= start:
            raise ValueError("End date must follow start date")
        result = []
        for skip in range(0, 20_000, 100):
            response = self.client.get(f"https://{CIVIC_HOST}/v1/Events", params={
                "$filter": f"eventDate ge {start}T00:00:00Z and eventDate lt {end}T00:00:00Z",
                "$orderby": "eventDate asc,id asc", "$top": 100, "$skip": skip,
            })
            response.raise_for_status()
            events = response.json()["value"]
            for event in events:
                if event.get("isPublished") == "Published" and not event.get("isDeleted"):
                    result.append(civic_event(event))
            if len(events) < 100:
                return result
        raise ValueError("Source window exceeded 20,000 records. Split the backfill.")


def civic_event(event: dict) -> DiscoveredMeeting:
    event_id = int(event["id"])
    meeting_key = f"civicclerk:{event_id}"
    # The tenant serializes meeting wall time with a Z suffix. Official agendas
    # confirm 16:00Z and 17:00Z are printed as 4 PM and 5 PM Central.
    starts = datetime.fromisoformat(event["startDateTime"]).replace(tzinfo=LOCAL)
    location = event.get("eventLocation") or {}
    title = event["eventName"]
    meeting = MeetingRef(
        key=meeting_key, body=event.get("eventCategoryName") or title, title=title,
        starts_at=starts, location=", ".join(str(location[field]) for field in
                                             ("address1", "address2", "city") if location.get(field)) or None,
        source_url=f"https://hattiesburgms.portal.civicclerk.com/event/{event_id}/files",
        status="cancelled" if ("cancelled" in title.lower() or "canceled" in title.lower()) else "scheduled",
    )
    files = sorted(event.get("publishedFiles") or [], key=lambda file: file.get("publishOn") or "")
    docs = {}
    for file in files:
        if not file.get("fileId") or not (file.get("url") or "").lower().endswith(".pdf"):
            continue
        fid = int(file["fileId"])
        kind = TYPE_MAP.get(file["type"].lower().strip(), Kind.attachment)
        key = f"{meeting_key}:{kind}" if kind in {Kind.agenda, Kind.minutes} else f"{meeting_key}:file:{fid}"
        published = file.get("publishOn")
        name = (file.get("name") or "").lower()
        # Only explicit approval/signature metadata gives published minutes
        # authority for automatic outcomes. Other minutes are reviewable.
        final = (kind == Kind.minutes and bool(re.search(r"\b(?:approved|signed)\b", name))
                 and not re.search(r"\b(?:draft|unsigned|unapproved|not (?:approved|signed))\b", name))
        docs[key] = DocumentRef(
            key=key, kind=kind, authoritative=final,
            url=f"https://{CIVIC_HOST}/v1/Meetings/GetMeetingFileStream(fileId={fid},plainText=false)",
            published_at=datetime.fromisoformat(published) if published and published[:4] != "0001" else None,
        )
    if meeting.status != "cancelled" and any(document.authoritative for document in docs.values()):
        meeting.status = "held"
    return DiscoveredMeeting(meeting=meeting, documents=list(docs.values()))


def legistar_january_2019() -> DiscoveredMeeting:
    """Legacy pinned meeting with a verified Final minutes label in Legistar."""
    ids = "GUID=79BB73AB-68B9-4536-8377-CC04C4B0E56B&ID=669983"
    meeting = MeetingRef(
        key="legistar:669983", body="City Council", title="City Council regular meeting",
        starts_at=datetime.combine(date(2019, 1, 8), time(17), LOCAL), location="Council Chambers", status="held",
        source_url=f"https://{LEGISTAR_HOST}/MeetingDetail.aspx?{ids}&Search=",
    )
    return DiscoveredMeeting(meeting=meeting, documents=[
        DocumentRef(key=f"{meeting.key}:{kind}", kind=kind, authoritative=kind == Kind.minutes,
                    url=f"https://{LEGISTAR_HOST}/View.ashx?{ids}&M={code}")
        for kind, code in [(Kind.agenda, "A"), (Kind.minutes, "M")]
    ])
