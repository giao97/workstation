from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.financial_research import FundamentalResearchContract
from src.schemas.standard_stock_report import StandardStockReport
from src.services.standard_report_service import StandardReportService


def test_section_coverage_is_never_prediction_confidence():
    now = datetime.now(timezone.utc)
    research = FundamentalResearchContract(stock_code='TEST', market='us', as_of=now,
        evidence=dict(stock_code='TEST', market='us', as_of=now), quality=dict(completeness_pct=0))
    report = StandardReportService.build({}, research).model_dump(mode='json')
    assert report['contract_version'] == '1.1'
    assert report['coverage_pct'] == 7.69  # data_evidence only, still limited
    assert report['confidence_pct'] is None
    assert len(report['sections']) == 13
    assert report['research_stance'] == 'insufficient'
    assert any('不是证据质量' in item for item in report['disclosures'])


def test_legacy_reports_read_as_coverage_without_mutating_archive():
    legacy = dict(contract_version='1.0', stock_code='TEST', market='us', as_of='2026-09-30T00:00:00Z',
                  status='partial', confidence_pct=38.46, sections=[], disclosures=['Historical'])
    before = deepcopy(legacy)
    result = StandardStockReport.model_validate(legacy).model_dump(mode='json')
    assert legacy == before
    assert result['coverage_pct'] == 38.46 and result['confidence_pct'] is None
    assert result['contract_version'] == '1.1' and len(result['disclosures']) == 2
    with pytest.raises(ValidationError):
        StandardStockReport.model_validate(dict(legacy, contract_version='1.1', confidence_pct=85))


def test_new_unknown_confidence_is_null_not_zero():
    report = StandardStockReport(contract_version='1.1', stock_code='TEST', market='us',
        as_of=datetime.now(timezone.utc), status='insufficient', sections=[]).model_dump(mode='json')
    assert report['confidence_pct'] is None and report['coverage_pct'] == 0
