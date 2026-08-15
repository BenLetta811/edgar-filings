"""Parse SEC companyfacts XBRL JSON into flat fact rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edgar_filings.client import pad_cik


@dataclass(frozen=True)
class XbrlFact:
    cik: str
    taxonomy: str
    concept: str
    unit: str
    period_start: str
    period_end: str
    fy: str
    fp: str
    form: str
    accession: str
    value: str
    filed: str


def parse_company_facts(payload: dict[str, Any], concept: str | None = None) -> list[XbrlFact]:
    cik = pad_cik(payload.get("cik", ""))
    wanted = concept.strip() if concept else None
    facts: list[XbrlFact] = []
    taxonomies = payload.get("facts") or {}
    for taxonomy, concepts in taxonomies.items():
        if not isinstance(concepts, dict):
            continue
        for concept_name, body in concepts.items():
            if wanted and concept_name != wanted:
                continue
            if not isinstance(body, dict):
                continue
            units = body.get("units") or {}
            for unit, observations in units.items():
                if not isinstance(observations, list):
                    continue
                for obs in observations:
                    if not isinstance(obs, dict):
                        continue
                    facts.append(
                        XbrlFact(
                            cik=cik,
                            taxonomy=str(taxonomy),
                            concept=str(concept_name),
                            unit=str(unit),
                            period_start=str(obs.get("start") or ""),
                            period_end=str(obs.get("end") or ""),
                            fy="" if obs.get("fy") is None else str(obs.get("fy")),
                            fp=str(obs.get("fp") or ""),
                            form=str(obs.get("form") or ""),
                            accession=str(obs.get("accn") or ""),
                            value="" if obs.get("val") is None else str(obs.get("val")),
                            filed=str(obs.get("filed") or ""),
                        )
                    )
    return facts
