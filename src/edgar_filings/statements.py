"""Build comparable financial-statement views from stored XBRL facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Sequence

StatementKind = str  # "duration" | "instant"


@dataclass(frozen=True)
class StatementLine:
    section: str
    label: str
    concepts: tuple[str, ...]
    kind: StatementKind
    unit: str = "USD"
    per_share: bool = False


STATEMENT_LINES: tuple[StatementLine, ...] = (
    StatementLine(
        "Income statement",
        "Revenue",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ),
        "duration",
    ),
    StatementLine(
        "Income statement",
        "Cost of revenue",
        ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
        "duration",
    ),
    StatementLine("Income statement", "Gross profit", ("GrossProfit",), "duration"),
    StatementLine(
        "Income statement",
        "Operating income",
        ("OperatingIncomeLoss",),
        "duration",
    ),
    StatementLine("Income statement", "Interest expense", ("InterestExpense", "InterestExpenseDebt"), "duration"),
    StatementLine(
        "Income statement",
        "Income before tax",
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ),
        "duration",
    ),
    StatementLine("Income statement", "Income tax", ("IncomeTaxExpenseBenefit",), "duration"),
    StatementLine("Income statement", "Net income", ("NetIncomeLoss", "ProfitLoss"), "duration"),
    StatementLine(
        "Income statement",
        "EPS (basic)",
        ("EarningsPerShareBasic",),
        "duration",
        unit="USD/shares",
        per_share=True,
    ),
    StatementLine(
        "Income statement",
        "EPS (diluted)",
        ("EarningsPerShareDiluted",),
        "duration",
        unit="USD/shares",
        per_share=True,
    ),
    StatementLine(
        "Balance sheet",
        "Cash & equivalents",
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "Cash",
        ),
        "instant",
    ),
    StatementLine("Balance sheet", "Current assets", ("AssetsCurrent",), "instant"),
    StatementLine("Balance sheet", "Total assets", ("Assets",), "instant"),
    StatementLine("Balance sheet", "Current liabilities", ("LiabilitiesCurrent",), "instant"),
    StatementLine("Balance sheet", "Long-term debt", ("LongTermDebt", "LongTermDebtNoncurrent"), "instant"),
    StatementLine("Balance sheet", "Total liabilities", ("Liabilities",), "instant"),
    StatementLine(
        "Balance sheet",
        "Stockholders' equity",
        ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        "instant",
    ),
    StatementLine(
        "Cash flow",
        "Operating cash flow",
        ("NetCashProvidedByUsedInOperatingActivities",),
        "duration",
    ),
    StatementLine(
        "Cash flow",
        "Investing cash flow",
        ("NetCashProvidedByUsedInInvestingActivities",),
        "duration",
    ),
    StatementLine(
        "Cash flow",
        "Financing cash flow",
        ("NetCashProvidedByUsedInFinancingActivities",),
        "duration",
    ),
    StatementLine(
        "Cash flow",
        "Net change in cash",
        (
            "CashAndCashEquivalentsPeriodIncreaseDecrease",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        ),
        "duration",
    ),
)

PREFERRED_FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F")


def statement_concepts() -> tuple[str, ...]:
    names: list[str] = []
    for line in STATEMENT_LINES:
        names.extend(line.concepts)
    return tuple(dict.fromkeys(names))


def _parse_day(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _duration_days(start: str, end: str) -> int:
    a, b = _parse_day(start), _parse_day(end)
    if not a or not b:
        return 0
    return max((b - a).days, 0)


def _form_rank(form: str) -> int:
    form = (form or "").upper()
    try:
        return PREFERRED_FORMS.index(form)
    except ValueError:
        return len(PREFERRED_FORMS)


def _parse_number(value: str) -> float | None:
    raw = (value or "").strip().replace(",", "")
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def format_amount(value: float | None, *, per_share: bool = False, scale: int = 1) -> str:
    if value is None:
        return "—"
    if per_share:
        formatted = f"{value:,.2f}"
        return f"({formatted[1:]})" if formatted.startswith("-") else formatted
    scaled = value / scale if scale else value
    if abs(scaled) >= 10:
        formatted = f"{scaled:,.0f}"
    else:
        formatted = f"{scaled:,.2f}"
    if formatted.startswith("-"):
        return f"({formatted[1:]})"
    return formatted


def choose_scale(values: Iterable[float]) -> tuple[int, str]:
    magnitudes = [abs(v) for v in values if v is not None]
    if not magnitudes:
        return 1, "USD"
    peak = max(magnitudes)
    if peak >= 1_000_000_000:
        return 1_000_000, "USD millions"
    if peak >= 1_000_000:
        return 1_000, "USD thousands"
    return 1, "USD"


def _matches_kind(row: Any, kind: StatementKind) -> bool:
    start = _field(row, "period_start")
    if kind == "instant":
        return start == ""
    return start != ""


def _unit_ok(row: Any, unit: str) -> bool:
    actual = _field(row, "unit")
    if unit == "USD":
        return actual == "USD"
    return actual.replace(" ", "") == unit.replace(" ", "") or actual == unit


def _field(row: Any, name: str) -> str:
    if hasattr(row, "keys"):
        value = row[name]
    else:
        value = getattr(row, name, "")
    return "" if value is None else str(value)


def _best_fact(rows: Sequence[Any], line: StatementLine) -> Any | None:
    eligible = [row for row in rows if _matches_kind(row, line.kind) and _unit_ok(row, line.unit)]
    if not eligible:
        eligible = [row for row in rows if _unit_ok(row, line.unit)]
    if not eligible:
        return None

    def concept_rank(row: Any) -> int:
        concept = _field(row, "concept")
        try:
            return line.concepts.index(concept)
        except ValueError:
            return 99

    eligible.sort(key=lambda row: _field(row, "filed"), reverse=True)
    eligible.sort(key=lambda row: _duration_days(_field(row, "period_start"), _field(row, "period_end")), reverse=True)
    eligible.sort(key=lambda row: _form_rank(_field(row, "form")))
    eligible.sort(key=concept_rank)
    return eligible[0]


def _period_label(end: str, fy: str, fp: str, form: str) -> str:
    fp = (fp or "").upper()
    year = fy or (end[:4] if end else "")
    if fp == "FY":
        head = f"FY {year}" if year else "FY"
    elif fp.startswith("Q"):
        head = f"{fp} {year}".strip()
    else:
        head = year or "Period"
    return f"{head} · {end}" if end else head


def build_statements(rows: Sequence[Any], max_periods: int = 5) -> dict[str, Any]:
    by_concept: dict[str, list[Any]] = {}
    for row in rows:
        by_concept.setdefault(str(row["concept"]), []).append(row)

    period_meta: dict[str, dict[str, str]] = {}
    for row in rows:
        end = str(row["period_end"] or "")
        if not end:
            continue
        current = period_meta.get(end)
        candidate = {
            "end": end,
            "fy": str(row["fy"] or ""),
            "fp": str(row["fp"] or ""),
            "form": str(row["form"] or ""),
            "filed": str(row["filed"] or ""),
        }
        if current is None or (candidate["filed"], -_form_rank(candidate["form"])) > (
            current["filed"],
            -_form_rank(current["form"]),
        ):
            period_meta[end] = candidate

    periods = sorted(period_meta.values(), key=lambda item: item["end"], reverse=True)[:max_periods]
    periods = list(reversed(periods))
    period_ends = [item["end"] for item in periods]

    numeric_values: list[float] = []
    prepared_rows: list[dict[str, Any]] = []
    for line in STATEMENT_LINES:
        amounts: dict[str, float | None] = {}
        raw_rows: list[Any] = []
        for concept in line.concepts:
            raw_rows.extend(by_concept.get(concept, []))
        for end in period_ends:
            subset = [row for row in raw_rows if str(row["period_end"] or "") == end]
            chosen = _best_fact(subset, line)
            number = _parse_number(str(chosen["value"])) if chosen is not None else None
            amounts[end] = number
            if number is not None and not line.per_share:
                numeric_values.append(number)
        if any(value is not None for value in amounts.values()):
            prepared_rows.append({"line": line, "amounts": amounts})

    scale, scale_label = choose_scale(numeric_values)
    sections: dict[str, list[dict[str, Any]]] = {}
    for item in prepared_rows:
        line: StatementLine = item["line"]
        display = {
            end: format_amount(value, per_share=line.per_share, scale=1 if line.per_share else scale)
            for end, value in item["amounts"].items()
        }
        sections.setdefault(line.section, []).append(
            {
                "label": line.label,
                "per_share": line.per_share,
                "amounts": display,
                "negative": {
                    end: (value is not None and value < 0) for end, value in item["amounts"].items()
                },
            }
        )

    return {
        "scale_label": scale_label,
        "periods": [
            {
                "end": item["end"],
                "label": _period_label(item["end"], item["fy"], item["fp"], item["form"]),
                "form": item["form"],
            }
            for item in periods
        ],
        "sections": [{"title": title, "rows": rows_} for title, rows_ in sections.items()],
    }
