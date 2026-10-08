# ETF 成分穿透与重复暴露检查

入口：持仓页 → **ETF 成分穿透 · 重叠检查**。这是研究资料和确定性计算，不是交易、估值或收益预测。本版支持美股上市基金的长仓、非杠杆净资产权重，一层穿透到已披露股票；不要求先把聊天中的持仓强行写进账本。

## 数据与范围

- 优先读取正式账本，复用新闻模块的只读股数重放，剔除已平仓、未来交易和零持仓。不调用估值，不刷新持仓缓存。可选一个活跃账户，否则合并全部活跃账户的代码集合。
- 数据库没有任何账户时，才可沿用现有显式 `MARKET_EVENT_PROFILE_PATH` 的代码级档案参考；任何空账户或停用账户也会阻止档案回填。档案保留原日期、7 天有效期和未知股数。此功能不外发档案或调用模型，不默认扫描文件，不把自选/配置目标当持仓。
- 成分库与持仓是不同集合。保存某只基金资料不会创建该基金持仓；没有匹配资料的持仓列为“类型或成分未确认”，不能直接认定它一定是股票或一定是基金。
- 当前没有自动发行人成分采集适配器。须阅读发行人资料后整理为受控 JSON，先校验预览，再明确确认保存。URL 只是证据入口，系统不自动访问或认证其内容。没有来源时保留空状态，不用示例或 LLM 猜测权重。

## 输入契约

下面仅是**合成格式说明，不是真实基金、行情或持仓**，不会默认导入产品库：

```json
{
  "fund_symbol": "DEMO",
  "fund_market": "us",
  "holdings_as_of": "2026-09-28",
  "source_name": "Synthetic format example only",
  "source_url": "https://example.com/holdings",
  "source_published_at": null,
  "methodology": "long_only_nav_weight_pct",
  "constituents": [
    {"market": "us", "symbol": "DEMOEQ", "name": "Synthetic equity", "kind": "equity", "weight_pct": "10.5"}
  ]
}
```

- `weight_pct=1` 表示基金净资产的 **1%**，不是 100%。采用 Decimal 求和，拒绝非有限数、零/负数、单项或合计超过 100%；不自动归一化或以容差补齐。超过 100% 的舍入误差也需核对来源后处理，不能静默隐藏。
- 每份最多 3,000 行。`market + symbol` 唯一，代码大写，市场小写；同代码不同市场不是同一上市证券。拒绝自身持有和重复行。`kind` 为 `equity / fund / cash / other`，基金套基金、现金和其他资产不算作已穿透股票。
- `holdings_as_of` 是发行人成分日期；`source_published_at` 是来源发布时间，有值必须含时区，没有则 `null`，不拿抓取/保存时间补成发布时间。日期不得在未来（美股基金按纽约日历核验）；已知发布时间不能早于成分日期。`recorded_at` 是系统实际留存 UTC 时点。
- 只接受无凭证、无敏感/跟踪参数的公开 HTTP(S) 来源链接。来源名称、日期和权重依赖人工核对；`source_reviewed=true` 是人工声明，**不是系统独立认证**。不能将名义敞口、杠杆基金、反向基金或衍生品的正数误填成普通 NAV 权重。
- 预览不保存。确认保存只追加 `etf_composition_snapshots`，不写账户、期初、成交、现金、预算、信号或订单。规范化后的内容 hash 防止重复保存；同日更正另存新版本，不覆盖旧行。按成分日期降序、同日 ID 降序选择最新；新导入的旧日资料不会覆盖新日资料。旧版本可通过 ID 读取。

## 计算口径

每个基金分别列出已披露权重、股票、嵌套基金、现金、其他和未披露权重。分项与 100% 对账；未披露不是现金，更不是零风险。

两只已持有基金的成分日期必须一致，且距当前纽约日期不超过 **7 个自然日**，才计算已披露股票交集：

`observed_overlap_pct(A,B) = Σ min(weight_A[i], weight_B[i])`

其中 `i` 只包含两份快照中 `kind=equity` 且 `market + symbol` 精确相同的行。总数计算全部交集，页面明细最多列前 20 项。两两交集不可跨多个基金直接相加，分母是每只基金自身 NAV，**不是用户总资产/净值/证券市值，也不是相关系数、收益概率或行业集中度**。

- 部分披露仅计算已观察到的交集；不将前十大重归一化为全持仓。即使显示 0%，也只表示输入范围内没有精确匹配，不能证明充分分散。
- 不同日期、过期/未来数据给 `null`，不是 0。7 日是本版保守资料检查规则，不是交易所标准，也不保证期间没有调仓。
- 持仓代码也出现在基金股票成分时，单列其基金内权重；不加上未知的用户直接持仓比例。
- 不自动合并 ADR/本地股、不同股类、跨市场上市实体，不递归穿透基金，不推断行业和因子暴露。这些均是未覆盖风险。
- 当前 `portfolio_exposure_pct=null`：没有接入同一时点估值、完整公司归属和行业映射，不输出组合金额、行业占比或加減仓金额。当前接口不提供历史 `as_of`，不能用于事前回测；当前留存的历史成分不证明过去已经可获得。

## API 与验收

沿用现有全局 API 认证，无新调度、通知或模型调用：

- `POST /api/v1/portfolio/etf-compositions/preview`：上面的快照对象，校验后返回内容 hash、覆盖与规范化预览。
- `POST /api/v1/portfolio/etf-compositions`：`{"snapshot": {...}, "source_reviewed": true}`，追加研究证据。
- `GET /api/v1/portfolio/etf-compositions/{id}`：只读保留版本。
- `GET /api/v1/portfolio/etf-exposure?account_id=...`：只读当前范围及重叠；无账户参数时使用全部范围。最多 100 个已持有代码，超出需选账户，不静默截断。

确定性测试覆盖部分披露、不归一化、日期错位、过期、重复/异常权重、未知发布时间、现金/嵌套基金、精确市场代码匹配、源链接安全、幂等/不可变更正、真实账本只读、档案未知数量，以及 UI 预览确认、输入变化失效、跨账户晚到响应和中英文。

真实发行人成分的完整性、身份映射正确性及发布时间仍需人工核验；合成测试和结构校验不构成真实数据验收。生产数据缺失时页面必须显示缺口。

回滚：撤回 ETF 页面组件及新增 API、schema/core/service/repository 代码即可停用；保留 `etf_composition_snapshots` 表和研究证据，不删除账本或改变持仓。共享只读持仓加载器可以保留，新闻行为兼容。暂时停用不需要撤销任何交易。

## English summary

The portfolio page now provides a local, source-traceable, one-level equity overlap review. Scope comes from read-only ledger replay, or the already configured symbol-only profile only when no accounts exist. Watchlists, targets, library membership and zero/closed holdings are not inferred as owned positions.

Import explicitly reviewed issuer evidence as JSON: preview first, then attest and save an immutable snapshot. No issuer adapter, model call, URL fetch, broker sync or order is involved. Publication time may be unknown and stays null; retention never substitutes for publication. NAV percentage units, dates, uniqueness, long-only weights and source URL safety are checked, but manual attestation is not independent verification.

Eligible same-date compositions (maximum age seven calendar days) yield the sum of minimum weights for exact market/symbol equity matches. Cash, nested funds and other assets are separate; undisclosed weight is not normalized away. Zero observed overlap does not establish diversification. Stale or date-mismatched pairs remain null. ADR/share-class/issuer merging, recursive funds, derivatives, factors, coherent portfolio valuation and sector totals are not implemented. Portfolio exposure stays null and pair percentages are not additive or account weights. No historical backtest eligibility is claimed.

Rollback the additive UI/API feature while retaining evidence tables. Existing holdings and all trading records remain unchanged. Deterministic and synthetic UI QA validate mechanics, not live issuer source quality.
