# -*- coding: utf-8 -*-
"""Deterministic scaffold for the fixed Standard stock report."""

from __future__ import annotations

from typing import Any, Dict, List

from src.schemas.financial_research import FundamentalResearchContract
from src.schemas.standard_stock_report import StandardReportSection, StandardStockReport


_SECTION_TITLES = {
    "investment_conclusion": "投资结论", "company_overview": "公司概览",
    "business_model": "商业模式与主营结构", "industry_competition": "行业与竞争格局",
    "financial_quality": "多期财务与质量", "peer_comparison": "同业比较",
    "valuation": "估值与安全边际", "events": "新闻事件与催化剂",
    "historical_analogs": "历史相似事件", "probability_outlook": "多周期概率展望",
    "conditional_action": "条件式关注与失效条件", "risks_countercase": "风险与反方观点",
    "data_evidence": "数据边界与证据来源",
}


class StandardReportService:
    @staticmethod
    def _legacy_data(context: Dict[str, Any], key: str) -> Dict[str, Any]:
        block = context.get(key)
        if not isinstance(block, dict):
            return {}
        data = block.get("data")
        return data if isinstance(data, dict) else block

    @classmethod
    def build(cls, context: Dict[str, Any], research: FundamentalResearchContract) -> StandardStockReport:
        evidence_ids = [record.evidence_id for record in research.evidence.records]
        quality = research.quality.model_dump(mode="json")
        valuation = cls._legacy_data(context, "valuation")
        institution = cls._legacy_data(context, "institution")
        boards = context.get("belong_boards") if isinstance(context.get("belong_boards"), list) else []
        section_data: Dict[str, Dict[str, Any]] = {
            "investment_conclusion": {},
            "company_overview": institution,
            "business_model": {},
            "industry_competition": {"belong_boards": boards} if boards else {},
            "financial_quality": {
                "periods": [period.model_dump(mode="json") for period in research.periods],
                "quality": quality,
            } if research.periods else {},
            "peer_comparison": {}, "valuation": valuation, "events": {},
            "historical_analogs": {}, "probability_outlook": {}, "conditional_action": {},
            "risks_countercase": {"financial_flags": quality.get("flags", [])} if quality.get("flags") else {},
            "data_evidence": {
                "point_in_time_status": research.evidence.point_in_time_status,
                "warnings": research.warnings,
                "sources": [record.model_dump(mode="json") for record in research.evidence.records],
            },
        }
        sections: List[StandardReportSection] = []
        for section_id, title in _SECTION_TITLES.items():
            facts = section_data[section_id]
            if facts:
                status = "limited" if section_id == "data_evidence" or research.warnings else "available"
                limitations = list(research.warnings) if section_id == "data_evidence" else []
            else:
                status = "missing"
                limitations = [f"{section_id}_data_missing"]
            sections.append(StandardReportSection(
                section_id=section_id, title=title, status=status, facts=facts,
                evidence_ids=evidence_ids if facts else [], limitations=limitations,
            ))
        available_count = sum(section.status != "missing" for section in sections)
        return StandardStockReport(
            stock_code=research.stock_code, market=research.market, as_of=research.as_of,
            status="partial" if available_count else "insufficient",
            contract_version="1.1",
            coverage_pct=round(available_count / len(sections) * 100.0, 2), sections=sections,
            disclosures=[
                "仅用于投研与决策辅助，不构成个性化投资建议。",
                "系统不连接券商、不自动下单；条件式关注区间必须由可复算数据生成。",
                "缺失章节保持 missing，不由模型臆造事实。",
                "coverage_pct 仅为非缺失章节占比（含 limited），不是证据质量、预测置信度或交易胜率；confidence_pct 未校准，保持 null。",
            ],
        )
