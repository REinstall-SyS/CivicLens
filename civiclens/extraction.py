"""Source-specific segmentation and evidence checks for Hattiesburg council PDFs."""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from hashlib import sha256

from civiclens.documents import Page
from civiclens.types import Kind, ModelObservation, State

EXTRACTION_VERSION = "hattiesburg-council/1"
HEADING = re.compile(
    r"(?m)^[ \t]*(?P<number>(?:[IVX]+\s*\.\s*-\s*)?\d+\.?|PH\.)[ \t]+"
    r"(?P<id>20\d{2}-\d{3,5})(?=[ \t\n]|$)[ \t]*"
)
SECTION = re.compile(r"(?im)^\s*(?:(?:[IVX]+\.)[ \t]+)?(?:ROUTINE|POLICY|CONSENT) AGENDA[ \t]*$")
FOOTER = re.compile(r"(?im)^[ \t]*City of Hattiesburg, MS[ \t]+Page \d+[^\n]*$")
MOTION = re.compile(r"\b(?:a\s+)?motion was made\b", re.I)
CARRIED = re.compile(r"\bm[o']?tion (?:carried|passed|received the affirmative vote)\b", re.I)
FAILED = re.compile(r"\bmotion (?:failed|did not carry|was defeated)\b", re.I)
VERB = re.compile(r"\bto\s+(?P<verb>approve|adopt|deny|reject|table|postpone|authorize|"
                  r"acknowledge|award|accept|confirm|ratify|repeal|rescind|amend|set|hold)\b", re.I)
TALLY = re.compile(r"\b(?:Yeas|Ayes):\s*(\d{1,2})\b.*?\bNays:\s*(\d{1,2})\b", re.I | re.S)
MONEY = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?(?![\d,]|\.\d)")
WARD = re.compile(r"\bWard\s+([1-5])\b", re.I)
ADDRESS = re.compile(r"\b\d{1,6}\s+(?:[A-Za-z0-9.'’-]+\s+){1,5}(?:Street|St\.?|Road|Rd\.?|"
                     r"Avenue|Ave\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Lane|Ln\.?)\b", re.I)
REFERENCE = re.compile(r"\b(?:ordinance|resolution)\s+(?:no\.?\s*|#\s*)?(\d+(?:-\d+)?)\b", re.I)
STOP_TITLE = re.compile(
    r"(?im)^[ \t]*(?:attachments?\s*:|(?:[IVX]+\.)[ \t]+[A-Z]|"
    r"(?:ROUTINE|POLICY|CONSENT) AGENDA\b|(?:Meeting )?Adjourn(?:ment)?\b|"
    r"Recess\b|Budget Presentations\b|In Memoriam\b|[0-9]+:[0-9]+[ \t]*[AP]\.?\s*M\.?\s*[-–]|"
    r"[A-Z][a-z]+, [A-Z][a-z]+ \d{1,2}, 20\d\d\s+City Council)"
)
TOPICS = {
    "Public hearings": r"public hearing",
    "Transportation": r"\b(?:bridge|road|sidewalk|street|traffic|easement)\b",
    "Land use": r"\b(?:zoning|variance|landmark|land development|land use|rezon\w*)\b",
    "Parks & recreation": r"\b(?:park|parks|recreation|playground)\b",
    "Water & utilities": r"\b(?:water|sewer|drainage|stormwater|utility|utilities)\b",
    "Budget & finance": r"\b(?:budget|claims docket|tax|grant|appropriat\w*|audit\w*|bid)\b",
    "Public safety": r"\b(?:fire department|police|emergency|public safety)\b",
    "Housing": r"\b(?:housing|affordable housing|roof repair)\b",
}


@dataclass(frozen=True)
class Citation:
    page: int
    start: int
    end: int
    quote: str
    method: str

    @property
    def key(self) -> str:
        return sha256(f"{self.page}:{self.start}:{self.end}:{self.quote}".encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Observation:
    official_id: str
    number: str
    title: str
    topic: str
    state: State
    evidence: tuple[Citation, ...]
    data: dict = field(default_factory=dict)
    method: str = "rules"
    confidence: float = 1.0


def normalize(text: str) -> str:
    return " ".join(text.split())


def topic_for(title: str) -> str:
    return next((topic for topic, pattern in TOPICS.items() if re.search(pattern, title, re.I)), "Government")


def claim_fields(text: str) -> dict:
    amounts = [format(Decimal(match[1].replace(",", "") + "." + (match[2] or "00")), ".2f")
               for match in MONEY.finditer(text)]
    return {
        "amounts": [{"value": value, "currency": "USD"} for value in dict.fromkeys(amounts)],
        "wards": sorted({int(match) for match in WARD.findall(text)}),
        "locations": list(dict.fromkeys(ADDRESS.findall(normalize(text)))),
        "references": list(dict.fromkeys(REFERENCE.findall(text))),
    }


def split_pages(pages: list[Page], start: int, end: int) -> tuple[Citation, ...]:
    output = []
    offset = 0
    for page in pages:
        left, right = max(0, start - offset), min(len(page.text), end - offset)
        if left < right:
            quote = page.text[left:right]
            if quote.strip():
                stripped = quote.strip()
                left += len(quote) - len(quote.lstrip())
                output.append(Citation(page.number, left, left + len(stripped), stripped, page.method))
        offset += len(page.text) + 1
        if offset >= end:
            break
    return tuple(output)


def recorded_action(text: str) -> tuple[State, dict]:
    """Recognize a recorded item-level motion followed by an explicit result."""
    normalized = normalize(text.replace("m'otion", "motion"))
    motions = list(MOTION.finditer(normalized))
    if len(motions) != 1:
        return State.unknown, {}
    rest = normalized[motions[0].end():]
    carried, failed = CARRIED.search(rest), FAILED.search(rest)
    if not carried or failed:
        return State.unknown, {}
    motion = rest[:carried.start()]
    motion = re.split(r"\bThere being\b", motion, maxsplit=1, flags=re.I)[0].strip()
    verb = VERB.search(motion)
    if not verb or re.search(r"\b(?:adjourn|agenda order|routine agenda|policy agenda)\b", motion, re.I):
        return State.unknown, {}
    tally = TALLY.search(rest[carried.end():])
    if tally and int(tally[1]) <= int(tally[2]):
        return State.unknown, {}
    state = State.approved
    if verb["verb"].lower() in {"table", "postpone"}:
        state = State.tabled
    if verb["verb"].lower() in {"reject", "deny"}:
        state = State.rejected
    data = {"motion": motion[verb.start():].rstrip(".")}
    if tally:
        data["vote"] = {"yeas": int(tally[1]), "nays": int(tally[2])}
        names = re.search(r"\b(?:Yeas|Ayes):\s*\d+\s*[-–]\s*(.*?)\s+Nays:", rest, re.I)
        if names:
            data["yeas_as_recorded"] = names[1]
    return state, data


def extract(pages: list[Page], kind: Kind, authoritative: bool) -> list[Observation]:
    if kind not in {Kind.agenda, Kind.minutes, Kind.notice}:
        return []
    text = "\n".join(page.text for page in pages)
    begin = 0
    if kind == Kind.minutes and "Published Agenda" in text[:500]:
        # CivicClerk signed minutes may prepend a facsimile agenda. The
        # clerk's narrative starts after the printed asterisk divider.
        divider = re.search(r"(?m)^[ \t]*\*{12,}[ \t]*$", text)
        if not divider:
            return []
        begin = divider.end()
    headings = list(HEADING.finditer(text, begin))
    output = []
    for index, heading in enumerate(headings):
        stop = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[heading.end():stop]
        section = SECTION.search(block)
        if section:
            stop = heading.end() + section.start()
            block = text[heading.end():stop]
        cutoff = min((match.start() for pattern in (STOP_TITLE, MOTION, FOOTER)
                      if (match := pattern.search(block))), default=len(block))
        title_block = block[:cutoff]
        title_block = re.sub(r"(?m)^[ \t]*\[(?:RES|ORD)[^\]\n]*[\])][ \t]*", "", title_block, flags=re.I)
        title = normalize(title_block)
        if len(title) < 8:
            continue
        title = title[:2400]
        citation = split_pages(pages, heading.start(), heading.end() + cutoff)
        state = State.proposed
        data = claim_fields(title)
        confidence = 0.96
        if kind == Kind.minutes:
            outcome, decision_data = recorded_action(block)
            state = outcome if authoritative else State.unknown
            motion = MOTION.search(block)
            discussion = re.search(r"\b(?:public hearing was held|discussion followed)\b", block, re.I)
            support = motion or discussion
            if support:
                citation += split_pages(pages, heading.end() + support.start(), stop)
            if state in {State.approved, State.rejected, State.tabled}:
                data.update(decision_data)
            elif discussion:
                state = State.discussed
            else:
                confidence = 0.55
        if any(item.method == "ocr" for item in citation):
            confidence = min(confidence, 0.8)
            if kind == Kind.minutes:
                state = State.unknown
                for field_name in ("vote", "motion", "yeas_as_recorded"):
                    data.pop(field_name, None)
        output.append(Observation(heading["id"], normalize(heading["number"]), title,
                                  topic_for(title), state, citation, data, confidence=confidence))
    return output


def confirm_model(candidate: ModelObservation, observation: Observation) -> bool:
    """Require exact scope and independently supported disposition."""
    if candidate.official_id != observation.official_id or candidate.outcome != observation.state:
        return False
    for span in observation.evidence:
        if span.key == candidate.evidence.segment_id and candidate.evidence.quote in span.quote:
            state, data = recorded_action(candidate.evidence.quote)
            return state == candidate.outcome and (
                candidate.vote is None or candidate.vote.model_dump() == data.get("vote")
            )
    return False
