# -*- coding: utf-8 -*-
"""Build the versioned research contract from the existing fundamental context."""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from src.schemas.financial_research import FinancialPeriod, FundamentalResearchContract
from src.schemas.research_evidence import (
    EvidenceRecord,
    EvidenceSnapshot,
    EvidenceSourceTier,
)
from src.services.financial_quality_service import compute_financial_quality
from src.services.standard_report_service import StandardReportService


_PRIMARY_PROVIDER_MARKERS = (
    "sec",
    "hkex",
    "sse",
    "szse",
    "bse",
    "cninfo",
    "company_filing",
)


def _utc_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.strptime(text[:10], "%Y-%m-%d")
            except ValueError:
                return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _date(value: Any) -> Optional[date]:
    parsed = _utc_datetime(value)
    return parsed.date() if parsed is not None else None


def _finite_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _first(payload: Dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in payload and payload.get(name) is not None:
            return payload.get(name)
    return None


def _source_tier(provider: str) -> EvidenceSourceTier:
    normalized = provider.lower()
    if any(marker in normalized for marker in _PRIMARY_PROVIDER_MARKERS):
        return EvidenceSourceTier.PRIMARY
    if any(marker in normalized for marker in ("akshare", "futu", "yfinance", "tushare", "realtime_quote")):
        return EvidenceSourceTier.STRUCTURED_SECONDARY
    return EvidenceSourceTier.UNKNOWN


def _period_type(payload: Dict[str, Any], period_end: date) -> str:
    raw = str(payload.get("period") or payload.get("period_type") or "").lower()
    if any(token in raw for token in ("annual", "year", "年度", "年报")):
        return "annual"
    if any(token in raw for token in ("quarter", "季度", "季报", "q1", "q2", "q3", "q4")):
        return "quarterly"
    if any(token in raw for token in ("interim", "half", "中期", "半年")):
        return "interim"
    if "ttm" in raw:
        return "ttm"
    if period_end.month == 12 and period_end.day == 31:
        return "annual"
    return "unknown"


class FundamentalResearchService:
    """Compatibility layer that enriches, but does not replace, fundamental_context."""

    @staticmethod
    def _build_evidence(
        *,
        stock_code: str,
        market: str,
        as_of: datetime,
        source_chain: Any,
    ) -> EvidenceSnapshot:
        records: List[EvidenceRecord] = []
        seen = set()
        entries = source_chain if isinstance(source_chain, list) else []
        for index, raw in enumerate(entries):
            item = raw if isinstance(raw, dict) else {"provider": str(raw)}
            provider = str(item.get("provider") or "unknown")
            result = str(item.get("result") or "unknown")
            dedupe_key = (provider, result)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            digest = hashlib.sha256(
                f"{stock_code}|{market}|{provider}|{result}|{as_of.isoformat()}|{index}".encode("utf-8")
            ).hexdigest()[:20]
            records.append(
                EvidenceRecord(
                    evidence_id=f"ev-{digest}",
                    stock_code=stock_code,
                    market=market,
                    provider=provider,
                    source_type="structured_data",
                    source_tier=_source_tier(provider),
                    result=result,
                    retrieved_at=as_of,
                    metadata={"duration_ms": item.get("duration_ms")},
                )
            )

        limitations: List[str] = []
        if not records:
            limitations.append("evidence_source_chain_missing")
        limitations.append("provider_publication_time_not_available")
        return EvidenceSnapshot(
            stock_code=stock_code,
            market=market,
            as_of=as_of,
            point_in_time_status="limited",
            records=records,
            limitations=limitations,
        )

    @staticmethod
    def _financial_periods(
        context: Dict[str, Any],
        evidence_ids: List[str],
    ) -> List[FinancialPeriod]:
        earnings = context.get("earnings") if isinstance(context.get("earnings"), dict) else {}
        earnings_data = earnings.get("data") if isinstance(earnings.get("data"), dict) else earnings
        if not isinstance(earnings_data, dict):
            return []

        raw_periods = earnings_data.get("financial_periods")
        reports: List[Dict[str, Any]] = [
            item for item in raw_periods if isinstance(item, dict)
        ] if isinstance(raw_periods, list) else []
        latest_report = earnings_data.get("financial_report")
        if not reports and isinstance(latest_report, dict):
            reports = [latest_report]

        periods: List[FinancialPeriod] = []
        seen = set()
        for report in reports:
            period_end = _date(_first(report, ("report_date", "period_end", "date")))
            if period_end is None:
                continue
            inferred_type = _period_type(report, period_end)
            dedupe_key = (period_end, inferred_type)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            published_at = _utc_datetime(
                _first(report, ("published_at", "announcement_date", "filing_date"))
            )
            periods.append(FinancialPeriod(
                period_end=period_end,
                period_type=inferred_type,
                currency=_first(report, ("currency", "currency_code")),
                provider=_first(report, ("provider", "source_provider", "source")),
                filing_version=_first(report, ("filing_version", "revision", "version")),
                source_url=report.get("source_url"),
                raw_snapshot_ref=report.get("raw_snapshot_ref"),
                published_at=published_at,
                revenue=_finite_float(_first(report, ("revenue", "total_revenue"))),
                gross_profit=_finite_float(report.get("gross_profit")),
                operating_income=_finite_float(
                    _first(report, ("operating_income", "operating_profit"))
                ),
                net_profit_parent=_finite_float(
                    _first(report, ("net_profit_parent", "net_income"))
                ),
                operating_cash_flow=_finite_float(
                    _first(report, ("operating_cash_flow", "cash_from_operations"))
                ),
                capital_expenditure=_finite_float(
                    _first(report, ("capital_expenditure", "capex"))
                ),
                total_assets=_finite_float(report.get("total_assets")),
                total_equity=_finite_float(
                    _first(report, ("total_equity", "shareholders_equity"))
                ),
                total_debt=_finite_float(report.get("total_debt")),
                cash_and_equivalents=_finite_float(
                    _first(report, ("cash_and_equivalents", "cash"))
                ),
                basic_eps=_finite_float(report.get("basic_eps")),
                roe_pct=_finite_float(_first(report, ("roe", "roe_pct"))),
                evidence_ids=evidence_ids,
            ))
        return sorted(periods, key=lambda item: item.period_end, reverse=True)[:12]

    @classmethod
    def enrich_context(
        cls,
        stock_code: str,
        context: Optional[Dict[str, Any]],
        *,
        as_of: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Return a shallow-compatible context with a versioned research block."""
        enriched = dict(context) if isinstance(context, dict) else {}
        resolved_as_of = _utc_datetime(as_of or enriched.get("as_of")) or datetime.now(timezone.utc)
        market = str(enriched.get("market") or "unknown")
        evidence = cls._build_evidence(
            stock_code=stock_code,
            market=market,
            as_of=resolved_as_of,
            source_chain=enriched.get("source_chain"),
        )
        evidence_ids = [record.evidence_id for record in evidence.records if record.result == "ok"]
        periods = cls._financial_periods(enriched, evidence_ids)
        warnings = list(evidence.limitations)
        if periods and periods[0].published_at is None:
            warnings.append("financial_report_publication_time_missing")
        if not periods:
            warnings.append("normalized_financial_periods_missing")

        contract = FundamentalResearchContract(
            stock_code=stock_code,
            market=market,
            as_of=resolved_as_of,
            evidence=evidence,
            periods=periods,
            quality=compute_financial_quality(periods),
            warnings=warnings,
        )
        research_status = "partial" if periods or evidence.records else "not_supported"
        enriched["as_of"] = resolved_as_of.isoformat()
        enriched["research"] = {
            "status": research_status,
            "coverage": {
                "evidence": "partial" if evidence.records else "missing",
                "financial_periods": "partial" if periods else "missing",
                "financial_quality": "partial" if periods else "missing",
            },
            "source_chain": list(enriched.get("source_chain") or []),
            "errors": [],
            "data": contract.model_dump(mode="json"),
            "standard_report": StandardReportService.build(enriched, contract).model_dump(mode="json"),
        }
        return enriched
