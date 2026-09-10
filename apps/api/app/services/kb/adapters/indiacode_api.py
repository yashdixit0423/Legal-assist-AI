"""India Code adapter, over the DSpace 7 REST API.

India Code moved to DSpace 7 behind an Angular front end, so the pages are a
JavaScript shell and cannot be scraped with an HTML parser. The REST API beneath
is better than the HTML was: it serves each section as its own item carrying the
section number, the marginal note, the text and the footnotes as separate
metadata fields, plus a repeal flag.

Nothing here touches the database or cleans text; it returns the portal's own
values and :mod:`app.services.kb.parse` decides what they mean.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import FetchError
from app.core.logging import get_logger
from app.services.kb.fetch import PoliteClient

logger = get_logger(__name__)

BASE_URL = "https://indiacode.gov.in"
API = "/server/api"
PAGE_SIZE = 100
# One Act's items (sections + schedules + the Act) comfortably fit this many pages.
MAX_PAGES = 40


def _first(metadata: dict[str, Any], key: str) -> str:
    values = metadata.get(key) or []
    if not values:
        return ""
    value = values[0].get("value")
    return "" if value is None else str(value)


def _date(raw: str) -> dt.date | None:
    """India Code mixes ISO and dd-mm-yyyy in the same field."""
    for pattern in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(raw.strip(), pattern).replace(tzinfo=dt.UTC).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class RawAct:
    """The Act-level item."""

    act_id: str
    uuid: str
    handle: str
    title: str
    act_number: str
    year: int | None
    enacted_on: dt.date | None
    commenced_on: dt.date | None
    ministry: str
    is_repealed: bool
    preamble: str
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass(frozen=True)
class RawSection:
    """One section-level item, exactly as the portal reports it."""

    section_number: str
    title: str
    body_html: str
    footnote_html: str
    order_number: int | None
    is_repealed: bool
    uuid: str
    handle: str
    collection: str
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def _act_from_item(item: dict[str, Any]) -> RawAct:
    md = item.get("metadata", {})
    year = _first(md, "dc.date.act_year")
    return RawAct(
        act_id=_first(md, "dc.identifier.act_id"),
        uuid=item.get("uuid", ""),
        handle=item.get("handle", ""),
        title=item.get("name") or _first(md, "dc.title"),
        act_number=_first(md, "dc.identifier.act_number"),
        year=int(year) if year.isdigit() else None,
        enacted_on=_date(_first(md, "dc.date.enact_date")),
        commenced_on=_date(_first(md, "dc.date.enforcement_date")),
        ministry=_first(md, "dc.identifier.ministry_name"),
        is_repealed=_first(md, "dc.identifier.repealed").lower() == "true",
        preamble=_first(md, "dc.identifier.preamble_description"),
        raw=item,
    )


def _section_from_item(item: dict[str, Any]) -> RawSection:
    md = item.get("metadata", {})
    order = _first(md, "dc.identifier.order_number")
    return RawSection(
        section_number=_first(md, "dc.identifier.section_number").strip(),
        title=(item.get("name") or _first(md, "dc.title")).strip(),
        body_html=_first(md, "dc.identifier.section_page_note"),
        footnote_html=_first(md, "dc.identifier.section_footnote"),
        order_number=int(order) if order.isdigit() else None,
        is_repealed=_first(md, "dc.identifier.repealed").lower() == "true",
        uuid=item.get("uuid", ""),
        handle=item.get("handle", ""),
        collection=_first(md, "dc.identifier.collection"),
        raw=item,
    )


def fetch_act_payload(client: PoliteClient, *, act_id: str, handle: str) -> dict[str, Any]:
    """Fetch the Act item and every item that shares its ``act_id``.

    Returns the payload that gets archived: one JSON document per Act, holding
    the portal's own responses so parsing can be replayed offline.
    """
    act_item = client.get_json(f"{API}/pid/find", {"id": f"hdl:{handle}"})
    if not act_item.get("uuid"):
        msg = f"handle {handle} did not resolve to an item"
        raise FetchError(msg)

    items: list[dict[str, Any]] = []
    for page in range(MAX_PAGES):
        result = client.get_json(
            f"{API}/discover/search/objects",
            {"query": act_id, "dsoType": "item", "size": PAGE_SIZE, "page": page},
        )
        search = result.get("_embedded", {}).get("searchResult", {})
        objects = search.get("_embedded", {}).get("objects", [])
        items.extend(
            entry["_embedded"]["indexableObject"]
            for entry in objects
            if "_embedded" in entry
        )
        info = search.get("page", {})
        if page + 1 >= int(info.get("totalPages", 1)):
            break
    else:
        msg = f"act {act_id} has more than {MAX_PAGES * PAGE_SIZE} items"
        raise FetchError(msg)

    logger.info("fetched_act", act_id=act_id, items=len(items))
    return {
        "fetched_at": dt.datetime.now(tz=dt.UTC).isoformat(),
        "source_url": f"{BASE_URL}/handle/{handle}",
        "act_id": act_id,
        "act_item": act_item,
        "items": items,
    }


def parse_payload(payload: dict[str, Any]) -> tuple[RawAct, list[RawSection]]:
    """Split an archived payload into the Act and its sections.

    Items belonging to a *different* act_id are dropped: the search endpoint is
    a full-text match, so a neighbouring Act that merely mentions this one's
    identifier would otherwise be ingested under the wrong citation.
    """
    act = _act_from_item(payload["act_item"])
    wanted = payload["act_id"]
    sections: list[RawSection] = []
    for item in payload["items"]:
        md = item.get("metadata", {})
        if _first(md, "dc.identifier.act_id") != wanted:
            continue
        if _first(md, "dc.identifier.collection") != "SECTION":
            continue
        section = _section_from_item(item)
        if section.section_number:
            sections.append(section)
    sections.sort(key=lambda s: (s.order_number if s.order_number is not None else 10**6))
    return act, sections
