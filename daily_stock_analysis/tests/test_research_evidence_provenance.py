"""Offline acceptance cases for the research evidence compatibility layer."""

from datetime import datetime, timezone
import unittest

from src.services.fundamental_research_service import FundamentalResearchService


class ResearchEvidenceProvenanceTest(unittest.TestCase):
    cutoff = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def enrich(self, entries, market="us", periods=None):
        context = {"market": market, "source_chain": entries}
        if periods is not None:
            context["earnings"] = {"data": {"financial_periods": periods}}
        return FundamentalResearchService.enrich_context(
            "DEMO", context, as_of=self.cutoff,
        )["research"]["data"]

    def record(self, **overrides):
        return {
            "provider": "company_filing", "result": "ok",
            "source_url": "https://example.com/filing/q2",
            "published_at": "2026-08-01T08:00:00+08:00",
            "retrieved_at": "2026-09-01T00:00:00Z",
            **overrides,
        }

    def test_us_preserves_document_provenance_and_utc(self):
        data = self.enrich([self.record(report_period="2026-Q2", filing_version="v2",
                                        content_hash="abc", raw_snapshot_ref="snapshot:1")])
        row = data["evidence"]["records"][0]
        self.assertEqual(row["source_url"], "https://example.com/filing/q2")
        self.assertEqual(row["published_at"], "2026-08-01T00:00:00Z")
        self.assertEqual(row["retrieved_at"], "2026-09-01T00:00:00Z")
        self.assertEqual(row["filing_version"], "v2")
        self.assertEqual(row["report_period"], "2026-Q2")
        self.assertEqual(row["content_hash"], "abc")
        self.assertEqual(row["raw_snapshot_ref"], "snapshot:1")
        self.assertEqual(data["evidence"]["point_in_time_status"], "limited")

    def test_cn_same_provider_distinct_announcements_are_not_merged(self):
        rows = [self.record(), self.record(source_url="https://example.com/filing/q1")]
        self.assertEqual(len(self.enrich(rows, market="cn")["evidence"]["records"]), 2)

    def test_document_ids_do_not_depend_on_input_order(self):
        rows = [self.record(), self.record(provider="sec.companyfacts",
                                          source_url="https://example.com/filing/q1")]
        first = self.enrich(rows)["evidence"]["records"]
        second = self.enrich(list(reversed(rows)))["evidence"]["records"]
        self.assertEqual({r["source_url"]: r["evidence_id"] for r in first},
                         {r["source_url"]: r["evidence_id"] for r in second})

    def test_exact_duplicate_is_deduplicated_but_revision_is_retained(self):
        row = self.record(filing_version="v1")
        rows = [row, dict(row), {**row, "filing_version": "v2"}]
        self.assertEqual(len(self.enrich(rows)["evidence"]["records"]), 2)

    def test_hk_future_publication_is_rejected_at_service_entry(self):
        with self.assertRaisesRegex(ValueError, "not available at as_of"):
            self.enrich([self.record(published_at="2026-10-01T08:00:01+08:00")], market="hk")

    def test_future_retrieval_without_publication_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not available at as_of"):
            self.enrich([self.record(published_at=None, retrieved_at="2026-10-02T00:00:00Z")])

    def test_known_publication_can_precede_later_retrieval_without_verification_claim(self):
        data = self.enrich([self.record(retrieved_at="2026-10-02T00:00:00Z")])
        self.assertEqual(data["evidence"]["records"][0]["retrieved_at"], "2026-10-02T00:00:00Z")
        self.assertEqual(data["evidence"]["point_in_time_status"], "limited")

    def test_legacy_missing_time_is_explicitly_limited(self):
        data = self.enrich([{"provider": "akshare", "result": "ok"}])
        self.assertIn("provider_retrieval_time_not_available", data["warnings"])
        self.assertIn("provider_publication_time_not_available", data["warnings"])
        self.assertTrue(data["evidence"]["records"][0]["metadata"]["retrieval_time_inferred_from_cutoff"])

    def test_invalid_timestamp_is_not_silently_truncated_to_date(self):
        with self.assertRaisesRegex(ValueError, "invalid evidence published_at"):
            self.enrich([self.record(published_at="2026-10-01 INVALID")])

    def test_older_period_missing_publication_is_also_reported(self):
        data = self.enrich([self.record()], periods=[
            {"period_end": "2026-06-30", "period_type": "quarterly",
             "published_at": "2026-08-01T00:00:00Z", "revenue": 120},
            {"period_end": "2025-06-30", "period_type": "quarterly", "revenue": 100},
        ])
        self.assertIn("financial_report_publication_time_missing", data["warnings"])

    def test_non_calendar_year_and_old_publication_are_not_rejected_by_age(self):
        data = self.enrich([self.record(published_at="2026-02-01T00:00:00Z")], market="hk", periods=[
            {"period_end": "2025-11-30", "period_type": "annual",
             "published_at": "2026-02-01T00:00:00Z", "revenue": 100},
        ])
        self.assertEqual(data["periods"][0]["period_end"], "2025-11-30")
        self.assertEqual(data["periods"][0]["period_type"], "annual")
        self.assertEqual(data["evidence"]["records"][0]["published_at"], "2026-02-01T00:00:00Z")

    def test_future_financial_period_remains_rejected(self):
        with self.assertRaisesRegex(ValueError, "were not published at as_of"):
            self.enrich([self.record()], periods=[
                {"period_end": "2026-06-30", "published_at": "2026-10-02T00:00:00Z"},
            ])


if __name__ == "__main__":
    unittest.main()
