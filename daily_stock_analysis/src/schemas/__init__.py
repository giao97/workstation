# -*- coding: utf-8 -*-
"""
===================================
DSA Schemas
===================================

Pydantic schemas for report output validation and internal contracts.
"""

from src.schemas.analysis_context_pack import (
    PACK_VERSION,
    AnalysisContextBlock,
    AnalysisContextItem,
    AnalysisContextPack,
    AnalysisSubject,
    ContextFieldStatus,
    DataQuality,
)
from src.schemas.report_schema import AnalysisReportSchema
from src.schemas.financial_research import (
    FINANCIAL_RESEARCH_CONTRACT_VERSION,
    FinancialPeriod,
    FinancialQualityMetrics,
    FundamentalResearchContract,
)
from src.schemas.research_evidence import (
    EVIDENCE_CONTRACT_VERSION,
    EvidenceRecord,
    EvidenceSnapshot,
    EvidenceSourceTier,
)
from src.schemas.standard_stock_report import (
    STANDARD_REPORT_CONTRACT_VERSION,
    StandardReportSection,
    StandardStockReport,
)

__all__ = [
    "AnalysisReportSchema",
    "PACK_VERSION",
    "AnalysisContextBlock",
    "AnalysisContextItem",
    "AnalysisContextPack",
    "AnalysisSubject",
    "ContextFieldStatus",
    "DataQuality",
    "EVIDENCE_CONTRACT_VERSION",
    "EvidenceRecord",
    "EvidenceSnapshot",
    "EvidenceSourceTier",
    "FINANCIAL_RESEARCH_CONTRACT_VERSION",
    "FinancialPeriod",
    "FinancialQualityMetrics",
    "FundamentalResearchContract",
    "STANDARD_REPORT_CONTRACT_VERSION",
    "StandardReportSection",
    "StandardStockReport",
]
