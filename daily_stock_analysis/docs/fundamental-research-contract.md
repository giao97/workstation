# 基本面研究与证据时点契约

本文档定义基本面研究第一阶段的内部数据契约。目标是让财务事实、派生指标和研究截止时间可追溯、可复算，并在不破坏现有报告的前提下逐步升级数据源。

## Standard 报告 1.1：覆盖率不是置信度

`standard_report` 使用 `coverage_pct = 非 missing 章节数 / 总章节数 × 100`（当前固定 13 章，含 limited）。它只说明章节有无内容，不衡量数据可靠性、预测置信度或交易胜率。即使只有“数据边界”章节可用，也会产生非零覆盖率，但不改变 `research_stance=insufficient`。

旧 `confidence_pct` 保留键名但在 1.1 输出中为 `null`，不以 0 假装有校准结果。内部 Standard 消费方已检查，无 Web/桌面数值渲染依赖；外部消费者必须按 `contract_version` 切换字段并允许 null，不能继续拿此字段算胜率或仓位。

读取 1.0 对象时只在内存把旧值映射到 `coverage_pct` 并添加口径说明，不改写历史归档。1.1 显式输入非空 `confidence_pct` 会被拒绝；没有样本外校准与适用范围证据前，不恢复数字置信度。回滚到旧代码会恢复旧标签，因此不得将旧版输出解释成真实置信度。

## 当前范围

- `fundamental_context` 原有的估值、增长、盈利和覆盖字段保持不变。
- Pipeline 在完成原有基本面采集后新增 `research` 区块，Agent 数据工具会保留该区块。
- 契约版本为 `1.0`，当前属于兼容接入阶段；A 股、港股、美股的完整多年/多季度采集映射及数据库持久化仍是后续工作。
- 本契约只支持投研和决策辅助，不包含券商连接、订单或自动交易能力。

## `research` 区块

```text
research.status
research.coverage
research.source_chain
research.errors
research.data.contract_version
research.data.stock_code / market / as_of
research.data.evidence
research.data.periods
research.data.quality
research.data.warnings
```

`status` 当前使用 `partial` 或 `not_supported`，避免在一手披露时间、原始快照和跨市场字段尚未完全接入时误报为完整覆盖。缺失数据保持 `null` 或空列表，不补零，也不交给 LLM 猜测。

## 证据和 `as_of`

每条 `EvidenceRecord` 可记录数据提供方、来源类型、可信等级、发布时间、生效时间、抓取时间、报告期、申报版本、内容哈希和原始快照引用。

- 所有时间统一转换为 UTC。
- 可用于研究的时间取 `published_at`；提供方没有发布时间时才退回 `retrieved_at`。
- `EvidenceSnapshot` 拒绝晚于 `as_of` 才可获得的证据。
- `FundamentalResearchContract` 拒绝发布时间晚于 `as_of` 的财务期间。
- 现有提供方大多尚未返回正式披露时间，因此当前快照标记为 `limited`，并显式输出 `provider_publication_time_not_available`。

这套限制防止把未来财报用于历史分析，但只有在后续接入一手公告时间和版本快照后，才能把状态升级为 `verified`。

## 多期财务标准字段

`FinancialPeriod` 当前统一以下基础字段：

- 期间：`period_end`、`period_type`、`published_at`、`currency`
- 利润表：`revenue`、`gross_profit`、`operating_income`、`net_profit_parent`、`basic_eps`
- 现金流：`operating_cash_flow`、`capital_expenditure`
- 资产负债表：`total_assets`、`total_equity`、`total_debt`、`cash_and_equivalents`
- 质量指标：`roe_pct`
- 可追溯性：`evidence_ids`

兼容层优先读取 `earnings.data.financial_periods`，没有多期数据时读取现有的 `earnings.data.financial_report`。最多保留最近 12 个期间，按报告期倒序排列。每个期间同时携带 `provider`、`filing_version`、`source_url` 和 `raw_snapshot_ref`，以便跨市场来源追踪和修订管理。

### 跨市场映射

- A 股：兼容 AkShare 的“指标为行、报告期为列”和“每个报告期一行”两种常见结构，币种默认 CNY，公告日期存在时纳入 `published_at`。
- 港股：将 Futu OpenD 的利润表、资产负债表、现金流量表和指标表按报告期合并；Futu 不可用时沿用 yfinance fallback。
- 美股：将 yfinance 的季度利润表、资产负债表和现金流量表按列日期合并，保留 `financialCurrency`。

适配器只映射提供方真实返回的字段。当前 yfinance 通常不提供正式申报发布时间，因此对应期间的 `published_at` 为空，历史可用时间退回首次抓取时间并保持 `limited`。

## 版本化持久化

`financial_statement_snapshots` 保存不可变的标准化财务版本：

- 唯一维度为股票、提供方、报告期、期间类型和内容哈希。
- 相同内容重复运行不会重复写入。
- 同一报告期内容发生变化时递增 `revision_no`，并通过 `supersedes_id` 指向上一版本。
- 明确的提供方版本写入 `filing_version`；没有版本号时使用本地 `r1`、`r2` 序列。
- `get_financial_periods_as_of()` 只返回截止时点已经发布或已经抓取的最新版本，修订后的数字不会覆盖历史视图。
- Pipeline 在保存原基本面快照的同时写入版本表；写入失败仍按既有 fail-open 语义降级。

数据库初始化通过 SQLAlchemy `create_all` 添加新表，并在 `schema_migrations` 记录 `2026-08-30-financial-research-snapshots-v1`。

## 可复算指标与异常标记

确定性代码计算以下指标：

| 指标 | 公式 |
| --- | --- |
| 毛利率 | `gross_profit / revenue * 100` |
| 营业利润率 | `operating_income / revenue * 100` |
| 净利率 | `net_profit_parent / revenue * 100` |
| 现金转换率 | `operating_cash_flow / net_profit_parent * 100` |
| 资产负债指标 | `total_debt / total_assets * 100` |
| 自由现金流 | `operating_cash_flow - abs(capital_expenditure)` |
| 同类期间增长率 | `(current - previous) / abs(previous) * 100` |

已实现的异常标记包括：盈利为正但经营现金流为负、现金转换偏弱、高债务占比、负毛利率、营收显著下降和净利润显著下降。阈值属于首版研究规则，后续应按市场和行业校准。

## 降级与兼容约定

- 研究契约构建失败时 Pipeline 记录警告并继续使用原 `fundamental_context`，不拖垮整只股票的分析。
- 原字段是当前消费者的兼容接口；新增消费者应优先读取 `research.data`。
- 没有报告期、发布时间或来源链时必须通过 `warnings` 和 `coverage` 披露。
- 只有完成跨市场字段映射、原始快照存储、财报修订版本和真实样例验收后，才允许将阶段 1 标记为完成。

## Standard 个股报告契约

`research.standard_report` 固定包含 13 个章节：投资结论、公司概览、商业模式、行业竞争、多期财务、同业比较、估值、事件、历史相似事件、概率展望、条件式关注、风险反方和数据证据。

每个章节都有 `available / limited / missing` 状态、结构化事实、证据 ID、限制说明和可选 narrative。确定性服务只填入已有事实；尚未建设的同业、事件、概率和条件区间保持 `missing`，不会生成看似完整的占位结论。报告固定披露不自动下单、不构成个性化投资建议。

## 源码与测试

- 证据契约：`src/schemas/research_evidence.py`
- 财务契约：`src/schemas/financial_research.py`
- 财务质量计算：`src/services/financial_quality_service.py`
- 兼容接入：`src/services/fundamental_research_service.py`
- Standard 报告：`src/schemas/standard_stock_report.py`、`src/services/standard_report_service.py`
- 版本化持久化：`src/storage.py`
- 回归测试：`tests/test_fundamental_research_contract.py`
- 跨市场与整体验收测试：`tests/test_cross_market_financial_research.py`

## 来源转换与离线验收（2026-10）

兼容层现在保留 source_chain 中显式提供的 source_url、published_at、effective_at、retrieved_at、report_period、filing_version、content_hash 和 raw_snapshot_ref。按完整来源身份去重，不再把同一提供方的不同公告或修订合为一条；证据 ID 不依赖列表顺序。已提供但格式非法的时间会报错，不截断为日期；显式发布时间或无发布时间时的抓取时间超过 as_of，仍由既有 EvidenceSnapshot 拒绝。

旧提供方不返回抓取时间时保留兼容回退，但 metadata.retrieval_time_inferred_from_cutoff 为 true，并输出 provider_retrieval_time_not_available；这不是实际抓取时间证明。任何期间缺少发布时间均输出财报时间缺失告警，不只检查最近一期。快照仍为 limited：字段齐全并不代表版本快照已验证。财报内容、电话会和公告前一致预期不会因为此改动自动补齐，既有财务期间与证据 ID 的逐条对应仍需上游提供更精确来源。

使用合成资料运行 `python -m pytest tests/test_research_evidence_provenance.py tests/test_fundamental_research_contract.py tests/test_standard_report_coverage.py tests/test_report_integrity.py`。其中 12 个来源验收案例覆盖跨市场、来源保留、同提供方多文档／修订、输入顺序、未来材料、非法时间、旧输入缺时点、非自然财年与历史期间。它们不调用模型，不评估股票收益，也不证明真实数据源已提供上述元数据。

回滚时仅撤回本次 fundamental_research_service.py、test_research_evidence_provenance.py 与本段文档／变更记录的差异；不回滚同目录的其他工作。证据 ID 的新算法只影响新生成记录，历史归档不重写；外部消费者不应跨版本假定 ID 与旧算法完全相同。
