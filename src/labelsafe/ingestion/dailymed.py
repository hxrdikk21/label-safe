"""
DailyMed REST client and Structured Product Labeling (SPL) XML parser.

The parser extracts the clinically relevant LOINC sections defined in
:mod:`labelsafe.knowledge.loinc_taxonomy`, strips XML markup while preserving
tables as pipe-delimited rows, and emits contract-conformant
``SourceDocument``, ``EvidencePassage`` and ``DrugProduct`` objects.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree as SafeET
from pydantic import HttpUrl

from src.labelsafe.core.contracts.document import SourceDocument
from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.core.contracts.product import DrugProduct
from src.labelsafe.ingestion.errors import UpstreamNotFoundError, UpstreamUnavailableError
from src.labelsafe.ingestion.hashing import fingerprint_text, sha256_hex, stable_uuid
from src.labelsafe.ingestion.http import RetryPolicy, SleepFn, get_with_retry
from src.labelsafe.knowledge.loinc_taxonomy import INACTIVE_INGREDIENTS, is_target_section, section_title

logger = logging.getLogger(__name__)

SOURCE_NAME: Final = "DailyMed"
DEFAULT_BASE_URL: Final = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
LABEL_URL_TEMPLATE: Final = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"
CHUNK_VERSION: Final = "2.1.0"  # 2.0.0: contextual header; 2.1.0: oversized blocks split
DEFAULT_MAX_PASSAGE_CHARS: Final = 1500

_NS: Final = "{urn:hl7-org:v3}"
_UNII_CODE_SYSTEM: Final = "2.16.840.1.113883.4.9"
_ACTIVE_CLASS_CODES: Final = frozenset({"ACTIB", "ACTIM", "ACTIR"})
_INACTIVE_CLASS_CODE: Final = "IACT"
_DOCUMENT_TYPE_STATUS: Final = {"34391-3": "Prescription", "34390-5": "OTC"}
_SPACES = re.compile(r"\s+")


def _q(tag: str) -> str:
    return f"{_NS}{tag}"


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


@dataclass(frozen=True, slots=True)
class SplSummary:
    """A DailyMed search hit."""

    setid: str
    title: str
    spl_version: int
    published_date: str


@dataclass(slots=True)
class ParsedSplLabel:
    """Everything extracted from a single SPL document."""

    document: SourceDocument
    passages: list[EvidencePassage]
    products: list[DrugProduct]
    sections_found: list[str]
    missing_excipient_data: bool
    inactive_ingredients: list[tuple[str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Text rendering
# --------------------------------------------------------------------------- #


def _clean_line(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def _inline_text(elem: Element) -> str:
    """Flattens inline markup; <br/> becomes a newline, everything else is concatenated."""
    parts: list[str] = [elem.text or ""]
    for child in elem:
        if _local(child.tag) == "br":
            parts.append("\n")
        elif _local(child.tag) != "footnote":
            parts.append(_inline_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _clean_block(text: str) -> str:
    lines = (_clean_line(line) for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def _render_table(table: Element) -> str:
    """Renders an SPL table as pipe-delimited rows so clinical tabular structure survives."""
    lines: list[str] = []
    caption = table.find(_q("caption"))
    if caption is not None:
        caption_text = _clean_line(_inline_text(caption))
        if caption_text:
            lines.append(caption_text)
    for row in table.iter(_q("tr")):
        cells = [
            _clean_line(_inline_text(cell)).replace("|", "/")
            for cell in row
            if _local(cell.tag) in {"td", "th"}
        ]
        if any(cells):
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _render_list(lst: Element) -> str:
    items = [_clean_block(_inline_text(item)) for item in lst.findall(_q("item"))]
    return "\n".join(f"- {item}" for item in items if item)


def _render_text_element(text_elem: Element) -> list[str]:
    """Converts an SPL <text> element into ordered plain-text blocks."""
    blocks: list[str] = []
    leading = _clean_block(text_elem.text or "")
    if leading:
        blocks.append(leading)
    for child in text_elem:
        name = _local(child.tag)
        if name == "table":
            block = _render_table(child)
        elif name == "list":
            block = _render_list(child)
        else:
            block = _clean_block(_inline_text(child))
        if block:
            blocks.append(block)
        tail = _clean_block(child.tail or "")
        if tail:
            blocks.append(tail)
    return blocks


def _section_code(section: Element) -> str | None:
    code = section.find(_q("code"))
    return code.get("code") if code is not None else None


def _section_blocks(section: Element) -> list[str]:
    """Renders a section and its nested subsections; subsection titles prefix their first block."""
    blocks: list[str] = []
    for child in section:
        name = _local(child.tag)
        if name == "text":
            blocks.extend(_render_text_element(child))
        elif name == "component":
            nested = child.find(_q("section"))
            if nested is None:
                continue
            nested_blocks = _section_blocks(nested)
            title_elem = nested.find(_q("title"))
            title = _clean_line(_inline_text(title_elem)) if title_elem is not None else ""
            if title and nested_blocks:
                nested_blocks[0] = f"{title}\n{nested_blocks[0]}"
            elif title:
                nested_blocks = [title]
            blocks.extend(nested_blocks)
    return blocks


def _collect_target_sections(root: Element) -> list[tuple[str, list[str]]]:
    """Walks the document in order, returning (loinc_code, blocks) for every target section."""
    found: list[tuple[str, list[str]]] = []

    def walk(elem: Element) -> None:
        for child in elem:
            name = _local(child.tag)
            if name == "excerpt":
                continue  # Highlights excerpts duplicate Full Prescribing Information text.
            if name == "section":
                code = _section_code(child)
                if is_target_section(code) and code is not None:
                    found.append((code, _section_blocks(child)))
                    continue
            walk(child)

    walk(root)
    return found


def build_contextual_header(drug_name: str, section_title: str, loinc_code: str, rxcui: str) -> str:
    """Prefix embedded and searched with every passage, so a chunk names its drug and section."""
    return (
        f"[DRUG: {drug_name.strip()}] "
        f"[SECTION: {section_title.strip()}] "
        f"[LOINC: {loinc_code.strip()}] "
        f"[RXCUI: {rxcui.strip()}]\n"
    )


def pack_with_header(blocks: list[str], header: str, max_chars: int) -> list[str]:
    """``pack_blocks`` within ``max_chars`` including the header, then prepends the header."""
    return [header + body for body in pack_blocks(blocks, max(1, max_chars - len(header)))]


_SENTENCE_END: Final = re.compile(r"(?<=[.!?;])\s+")


def split_block(block: str, max_chars: int) -> list[str]:
    """A block longer than ``max_chars`` (typically a whole table) as pieces of at most ``max_chars``:
    split between lines (table rows) first, then between sentences, hard-wrapped only as a last resort."""
    if len(block) <= max_chars:
        return [block]
    units: list[str] = []
    for line in block.split("\n"):
        for sentence in [line] if len(line) <= max_chars else _SENTENCE_END.split(line):
            while len(sentence) > max_chars:
                units.append(sentence[:max_chars])
                sentence = sentence[max_chars:]
            if sentence.strip():
                units.append(sentence)
    pieces: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + 1 + len(unit) > max_chars:
            pieces.append(current)
            current = unit
        else:
            current = f"{current}\n{unit}" if current else unit
    if current:
        pieces.append(current)
    return pieces


def pack_blocks(blocks: list[str], max_chars: int = DEFAULT_MAX_PASSAGE_CHARS) -> list[str]:
    """Greedily packs blocks into passages of at most ``max_chars``; oversized blocks are split first,
    since the embedding model and reranker only read the first ~512 tokens of a passage."""
    blocks = [piece for block in blocks for piece in split_block(block, max_chars)]
    passages: list[str] = []
    current: list[str] = []
    size = 0
    for block in blocks:
        added = len(block) + (2 if current else 0)
        if current and size + added > max_chars:
            passages.append("\n\n".join(current))
            current, size = [], 0
            added = len(block)
        current.append(block)
        size += added
    if current:
        passages.append("\n\n".join(current))
    return passages


# --------------------------------------------------------------------------- #
# Product data
# --------------------------------------------------------------------------- #


def _coded_unii(elem: Element | None) -> str | None:
    if elem is None:
        return None
    code = elem.find(_q("code"))
    if code is None or code.get("codeSystem") != _UNII_CODE_SYSTEM:
        return None
    return code.get("code") or None


def _strength(ingredient: Element) -> str | None:
    numerator = ingredient.find(f"{_q('quantity')}/{_q('numerator')}")
    if numerator is None or not numerator.get("value"):
        return None
    strength = f"{numerator.get('value')} {numerator.get('unit', '')}".strip()
    denominator = ingredient.find(f"{_q('quantity')}/{_q('denominator')}")
    if denominator is not None and denominator.get("value") not in {None, "1"}:
        strength += f"/{denominator.get('value')} {denominator.get('unit', '')}".rstrip()
    elif denominator is not None and denominator.get("unit") not in {None, "1"}:
        strength += f"/{denominator.get('unit')}"
    return strength


def _parse_products(
    root: Element, *, setid: str, rxcui: str, marketing_status: str, jurisdiction: str
) -> tuple[list[DrugProduct], list[tuple[str, str]]]:
    products: list[DrugProduct] = []
    inactive_all: dict[str, str] = {}
    for outer in root.iter(_q("manufacturedProduct")):
        inner = outer.find(_q("manufacturedProduct"))
        if inner is None:
            continue
        ndc_elem = inner.find(_q("code"))
        ndc = ndc_elem.get("code") if ndc_elem is not None else None
        name_elem = inner.find(_q("name"))
        brand = _clean_line(_inline_text(name_elem)) if name_elem is not None else ""
        if not ndc or not brand:
            continue
        generic_elem = inner.find(f"{_q('asEntityWithGeneric')}/{_q('genericMedicine')}/{_q('name')}")
        generic = _clean_line(_inline_text(generic_elem)) if generic_elem is not None else brand
        form_elem = inner.find(_q("formCode"))
        route_elem = outer.find(f"{_q('consumedIn')}/{_q('substanceAdministration')}/{_q('routeCode')}")

        active_uniis: list[str] = []
        inactive_uniis: list[str] = []
        strengths: list[str] = []
        for ingredient in inner.findall(_q("ingredient")):
            class_code = ingredient.get("classCode", "")
            substance = ingredient.find(_q("ingredientSubstance"))
            if substance is None:
                continue
            if class_code in _ACTIVE_CLASS_CODES:
                moiety = substance.find(f"{_q('activeMoiety')}/{_q('activeMoiety')}")
                unii = _coded_unii(moiety) or _coded_unii(substance)
                if unii and unii not in active_uniis:
                    active_uniis.append(unii)
                strength = _strength(ingredient)
                if strength:
                    strengths.append(strength)
            elif class_code == _INACTIVE_CLASS_CODE:
                unii = _coded_unii(substance)
                sub_name = substance.find(_q("name"))
                if unii and unii not in inactive_uniis:
                    inactive_uniis.append(unii)
                    if sub_name is not None:
                        inactive_all.setdefault(unii, _clean_line(_inline_text(sub_name)))

        products.append(
            DrugProduct(
                ndc=ndc,
                rxcui=rxcui,
                brand_name=brand,
                generic_name=generic or brand,
                dosage_form=(form_elem.get("displayName") if form_elem is not None else None) or "UNKNOWN",
                route=(route_elem.get("displayName") if route_elem is not None else None) or "UNKNOWN",
                strength=" / ".join(strengths) or "UNKNOWN",
                spl_setid=setid,
                active_ingredient_uniis=active_uniis,
                inactive_excipient_uniis=inactive_uniis,
                marketing_status=marketing_status,
                jurisdiction=jurisdiction,
            )
        )
    return products, sorted(inactive_all.items())


# --------------------------------------------------------------------------- #
# Document parsing
# --------------------------------------------------------------------------- #


def _format_effective_date(raw: str | None) -> str | None:
    if not raw or len(raw) < 8 or not raw[:8].isdigit():
        return None
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def parse_spl(
    xml: str | bytes,
    *,
    rxcui: str,
    jurisdiction: str = "US",
    max_passage_chars: int = DEFAULT_MAX_PASSAGE_CHARS,
    retrieved_at: datetime | None = None,
) -> ParsedSplLabel:
    """
    Parses an SPL XML document into canonical contracts.

    Passage identifiers are deterministic UUIDv5 values derived from the SetID,
    version, LOINC code and passage index, so re-parsing the same label is idempotent.
    """
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    try:
        root = SafeET.fromstring(raw)
    except (SafeET.ParseError, ValueError) as exc:  # ValueError covers defusedxml entity/DTD rejections
        raise UpstreamUnavailableError(SOURCE_NAME, f"malformed SPL XML: {exc}") from exc

    set_id_elem = root.find(_q("setId"))
    setid = set_id_elem.get("root") if set_id_elem is not None else None
    if not setid:
        raise UpstreamUnavailableError(SOURCE_NAME, "SPL document has no setId")
    version_elem = root.find(_q("versionNumber"))
    version = (version_elem.get("value") if version_elem is not None else None) or "1"
    effective_elem = root.find(_q("effectiveTime"))
    effective_date = _format_effective_date(
        effective_elem.get("value") if effective_elem is not None else None
    )
    title_elem = root.find(_q("title"))
    title = _clean_line(_inline_text(title_elem)) if title_elem is not None else ""
    doc_type = _section_code(root) or ""

    document = SourceDocument(
        document_id=setid,
        source_name=SOURCE_NAME,
        source_url=HttpUrl(LABEL_URL_TEMPLATE.format(setid=setid)),
        version=version,
        effective_date=effective_date,
        title=title or setid,
        sha256_hash=sha256_hex(raw),
        jurisdiction=jurisdiction,
        rxcui_primary=rxcui,
        retrieval_timestamp=retrieved_at or datetime.now(UTC),
    )

    products, inactive = _parse_products(
        root,
        setid=setid,
        rxcui=rxcui,
        marketing_status=_DOCUMENT_TYPE_STATUS.get(doc_type, "Prescription"),
        jurisdiction=jurisdiction,
    )
    drug_name = products[0].generic_name if products else (title or setid)

    passages: list[EvidencePassage] = []
    sections_found: list[str] = []
    next_index: dict[str, int] = {}
    seen_hashes: set[str] = set()
    for code, blocks in _collect_target_sections(root):
        if code not in sections_found:
            sections_found.append(code)
        header = build_contextual_header(drug_name, section_title(code), code, rxcui)
        for content in pack_with_header(blocks, header, max_passage_chars):
            digest = fingerprint_text(content)
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            index = next_index.get(code, 0)
            next_index[code] = index + 1
            passages.append(
                EvidencePassage(
                    passage_id=str(stable_uuid(setid, version, code, str(index), CHUNK_VERSION)),
                    document_id=setid,
                    rxcui=rxcui,
                    loinc_section_code=code,
                    section_title=section_title(code),
                    passage_index=index,
                    content=content,
                    token_count=len(content.split()),
                    sha256_hash=digest,
                    chunk_version=CHUNK_VERSION,
                )
            )

    missing_excipients = INACTIVE_INGREDIENTS.code not in sections_found
    if missing_excipients:
        logger.warning("SPL %s v%s has no inactive ingredient section (51727-6)", setid, version)
    return ParsedSplLabel(
        document=document,
        passages=passages,
        products=products,
        sections_found=sections_found,
        missing_excipient_data=missing_excipients,
        inactive_ingredients=inactive,
    )


# --------------------------------------------------------------------------- #
# REST client
# --------------------------------------------------------------------------- #


class DailyMedClient:
    """Async client for the DailyMed v2 REST web services."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = DEFAULT_BASE_URL,
        retry_policy: RetryPolicy | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._policy = retry_policy or RetryPolicy()
        self._sleep = sleep

    async def _get(self, path: str, params: dict[str, str | int] | None = None) -> httpx.Response:
        return await get_with_retry(
            self._client,
            f"{self._base_url}/{path}",
            source=SOURCE_NAME,
            params=params,
            policy=self._policy,
            sleep=self._sleep,
        )

    async def search_spls(
        self, *, drug_name: str | None = None, rxcui: str | None = None, page_size: int = 10
    ) -> list[SplSummary]:
        """Searches SPL metadata by drug name or RxCUI. Raises UpstreamNotFoundError when empty."""
        if not drug_name and not rxcui:
            raise ValueError("drug_name or rxcui is required")
        params: dict[str, str | int] = {"pagesize": page_size}
        if drug_name:
            params["drug_name"] = drug_name
        if rxcui:
            params["rxcui"] = rxcui
        response = await self._get("spls.json", params)
        try:
            payload: dict[str, Any] = response.json()
            hits = [
                SplSummary(
                    setid=str(item["setid"]),
                    title=str(item.get("title", "")),
                    spl_version=int(item.get("spl_version", 1)),
                    published_date=str(item.get("published_date", "")),
                )
                for item in payload.get("data", [])
            ]
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamUnavailableError(SOURCE_NAME, f"malformed search payload: {exc}") from exc
        if not hits:
            raise UpstreamNotFoundError(SOURCE_NAME, f"no SPLs for {drug_name or rxcui}")
        return hits

    async def fetch_spl_xml(self, setid: str) -> str:
        """Downloads the raw SPL XML for a SetID."""
        response = await self._get(f"spls/{setid}.xml")
        return response.text

    async def fetch_label(self, setid: str, *, rxcui: str, jurisdiction: str = "US") -> ParsedSplLabel:
        """Downloads and parses an SPL label."""
        return parse_spl(await self.fetch_spl_xml(setid), rxcui=rxcui, jurisdiction=jurisdiction)
