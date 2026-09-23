# Fundamental Research and Point-in-Time Evidence Contract

This document defines the first internal contract for traceable fundamental research. It preserves the existing `fundamental_context` fields and adds a versioned `research` block to the analysis pipeline and Agent data tools.

The `1.0` contract contains a UTC `as_of` cutoff, evidence records, normalized financial periods, deterministic quality metrics, coverage, and warnings. Missing values remain null or absent; they are never replaced with zero or inferred by an LLM.

Evidence availability uses `published_at` when known and falls back to `retrieved_at`. Evidence and financial periods that were unavailable at the research cutoff are rejected. Because most current providers do not expose official filing publication times or immutable raw snapshots, the initial point-in-time status remains `limited`, not `verified`.

Normalized fields currently cover reporting period, currency, revenue, gross and operating profit, parent net profit, operating cash flow, capital expenditure, assets, equity, debt, cash, EPS, ROE, and evidence IDs. The compatibility adapter reads `earnings.data.financial_periods`, or the legacy `financial_report` when multi-period data is unavailable.

Deterministic calculations include margins, cash conversion, debt to assets, free cash flow, comparable-period growth, completeness, and initial anomaly flags. Formulas are included in the payload so results can be reproduced.

Cross-market mapping now supports common AkShare A-share layouts, Futu OpenD Hong Kong statement bundles, and yfinance US/HK statement frames. The immutable `financial_statement_snapshots` table deduplicates identical content, chains corrected filings through revision numbers and `supersedes_id`, and provides point-in-time reads that do not overwrite historical views.

`research.standard_report` defines 13 fixed sections. Each section is explicitly available, limited, or missing and carries structured facts, evidence IDs, and limitations. Missing peer, event, forecast, or conditional-action data is not invented.

Official publication timestamps and raw source snapshots remain provider-dependent. The contract supports research and decision assistance only; it does not add broker connectivity or automatic trading.
