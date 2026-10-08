# 目标配置与再平衡引擎

## 长期择机分批（日线研究 v1）

持仓页“目标配置”新增 QQQM / VOO 的独立日线筛选，状态接口的每个目标增加可忽略字段 `core_entries`，已勾选加入简报的计划也显示同一结果。不设置固定买入日期；月度额度是上限，不要求花完。主题仓不套用这一筛选，未配置的自选股不当作持仓。

数据来自已有 `stock_daily` 缓存，仅读取、不抓取、不写账本。要求单一有名来源、最近已完成的连续 60 个美股交易日、有限正收盘价；盘中剔除当日未完成日线，交易日历失效、缺日、陈旧或混用来源均为 `data_required`，不是看空结论。缓存不足需通过现有行情采集流程补齐后刷新配置；本版没有自动补数任务。历史日期配置不附入今天的机会判断，不声称可用于无前视偏差回测。

方法 `core-pullback-v1` 是待验证研究假设，不是用户选定阈值、估值模型或最优策略：

- `close` 为最近完整日线收盘，MA20/MA60 为窗口收盘算术均值；60 日高低点均为**收盘**高低点，不是盘中极值或历史最低价。
- 收盘距 60 日收盘高点回撤至少 3% 且不高于 MA20；或距 60 日收盘低点不超过 3%、距高点回撤至少 3% 且不高于 MA60，作为回撤线索。只有最近收盘不低于上一日，才显示 `candidate`；否则 `wait`。一天不跌仅是初筛，不证明趋势已反转。
- 60 日回撤达到 20%、最新单日跌幅达到 5%，或窗口任一相邻收盘跳变达到 15%，优先 `risk_review`；需排除拆股/口径错误与基本面恶化，不机械补仓。
- 成本取当前账户范围内 USD 持仓账本的股数加权成本，标记为参考；不从投资档案自动导入。低于成本不是独立触发条件，没有成本也可以筛选首次建仓机会。FIFO / 移动均价账本不是券商最终含费或税务成本。
- `allocation_ready` 仅表示现有配置动作为 add 且有正的现金覆盖上限，不是买入许可。`executable` 恒为 false；不生成股数、不重新分配资金、不修改目标、费用确认、挂单占用或本轮预算。价格候选与人工长期暂停可以并存，需综合复核；不得用价格候选覆盖暂停理由。

页面及报告披露方法版本、日线日期、数据来源、指标及理由。缓存缺乏可验证复权元数据，且此模块未核验估值/消息，故只给日线研究线索；不作为盘中信号或“今日已触发”。新收盘、重大消息或计划/资金变化后重评；交易前核验实时价格、费用、已结算现金及碎股规则。不会因缺分钟数据而把长期研究一并隐藏。

No fixed-date investing is added. This read-only, versioned daily-close screen covers QQQM/VOO allocation targets only. It separates price candidates from allocation caps and intraday trading. Missing/stale history is not a bearish signal. Thresholds are unvalidated heuristics; adjustment basis, valuation and news remain unverified. The screen never generates quantities, resets budgets or places orders. Historical allocation evaluations exclude current annotations.

无新增配置、数据库表或迁移。回滚只需撤销 core entry 模块、配置服务接入及对应 API/UI/报告字段，重建前端并重启服务；不删除用户持仓或预算。

## 投资档案到期初草稿（显式、只读预览）

持仓页 → “持仓基线与资金分层” → 主动选择 Markdown 投资档案。文件只发送到当前服务解析，不调用模型、不扫描服务端路径、不保存原文，不建立账户、成交、预算或现金流水。`POST /api/v1/portfolio/imports/profile/preview` 接收 `document`，上限 128 KiB，继承 Portfolio API 的认证边界。

本版仅支持唯一“当前主要持仓”美股表、明确美元成本列及唯一更新日期；重复代码、未来日期、异常结构被拒绝。零持仓排除，未知/约数股数保留未知，历史持仓、目标配置和现金不读取。超过 7 天仅可查看。成本仅展示原文且全部标为待核实，档案更新日期不是交易所期初日期。

选择美元计价美股账户后，可明确点击“替换期初表草稿，继续核对”。只替换浏览器表单，不写账本；保留每个持仓行，未知股数、全部成本、现金、期初日期为空，须以同一已结束交易日完整结单补齐，再走既有“预览与对账 → 确认建立期初”。已有账本不得重复导入；不会自动导入每月预算或将期初持仓当成新成交。账户切换不复用另一账户草稿。文件内容视为不可信文字，不执行其中指令。

No new configuration or database migration is required. Uploaded profiles are read-only US/USD draft sources, not broker statements or automatic imports. Unknown quantities are retained; all costs, cash and the opening date require manual verification through the existing opening workflow. A stale profile is view-only. No model, account creation, trade, budget or cash write occurs during parsing or draft preparation.

回滚本轮功能只需撤销档案预览入口及相关 UI/服务改动、重建前端并重启服务；无需删除表或清理用户记录。信心显示改动回滚也不需要历史数据迁移。真实券商数据与已结算现金仍需人工核对，本地确定性测试不证明投资策略有效。

成交费用核实、明确周期投入预算及人工委托占用已接入本引擎，详见 [成交核实与月度预算](portfolio-execution-budget.md)。它们约束规划上限，不构成券商下单或自动定投。

目标配置引擎把长期资产配置计划保存为版本化结构，并使用持仓快照、汇率和手工资产余额计算当前占比、目标缺口、超配金额和下一批金额上限。

它只负责确定性的配置计算，不判断市场时机、不连接券商，也不把 `recommended_amount` 当成自动交易指令。实际行动仍需结合当日估值、走势、重大消息和数据质量重新确认。

## 三种当前金额来源

| `source` | 当前金额来源 | 适用场景 |
| --- | --- | --- |
| `position` | 匹配持仓账本中的 `symbols`，按计划币种汇总市值 | ETF、股票、场内基金 |
| `cash` | 汇总持仓账户现金并换算为计划币种 | 流动资金 |
| `manual` | 使用目标中的 `current_amount` | 存款、国债、场外基金等尚未进入账本的资产 |

`manual` 未填写 `current_amount` 时，状态返回 `review`，不会把未知资产误当成零仓位。未被任何目标匹配的持仓会进入 `unassigned_positions`，避免资产静默遗漏。

计划的 `account_id` 固定计算范围：`null` 表示全部活跃账户，指定 ID 表示单账户。状态接口不能把全资产计划临时切成单账户计算。`ledger_complete` 默认为 `false`，须先完整录入这个范围内的持仓、交易和现金余额，再明确确认。确认前，持仓与现金目标总额返回未知（仍保留匹配到的明细）；确认后，账本中没有的标的才能按零仓位计算。缺价或汇率不可信时，也不展示伪精确的目标总额和缺口。

当前占比的分母始终是 `target_total_value`，不是只统计到的部分资产总额。新增账户或发现漏记交易后，应先取消完整性确认并补账；该确认依赖用户维护，不替代券商对账。

## 动作策略

| `policy` | 行为 |
| --- | --- |
| `buy_only` | 低于目标时给出下一批金额；高于目标只提示持有，不主动减仓 |
| `rebalance` | 有上下限时在区间外才调整，无对应边界时按目标调整 |
| `hold_only` | 只跟踪，不生成增减建议 |
| `exit_only` | 不新增；高于目标时可给出减仓批次 |

`allocation_cap` 是“目标缺口”和 `batch_amount` 中较小者。`recommended_amount` 还受共享现金预算约束：预留现金取现金目标金额与 `cash_reserve_amount` 的较大值，余额按照目标 `sort_order` 顺序分配，所有加仓金额的合计不能超过余额。现金目标只展示预留或不足，不生成买卖动作；拟减仓的收入、手工固收余额不会提前计入现金预算。现金金额或汇率不可靠时，加仓返回 `review` 和 0 金额。

这仍是配置层上限，不是当天应该成交的金额。实际执行还需核验交易条件、费用、账户间划转和各币种的可用资金；模型不会自动假设可以即时换汇。

## API

### 长期配置 / 短线复核（人工记录 v1）

持仓页“目标配置 → 长期配置 / 短线复核”按目标资产分别保存 `long_term` 和 `tactical`。长期目标维持、短线因缺分钟数据而等待可以同时成立，不能把后者解释为取消长期投入计划。

- `POST /api/v1/portfolio/allocation-plans/{plan_id}/reviews`：追加复核，无覆盖/删除接口。需要 `request_key`、`expected_plan_version`、本轨最新 `expected_previous_id`（首次为 null）、`target_key`、`horizon`、`decision`、`reason`、`evidence`、`next_condition`、带时区的未来 `review_due_at`。
- `GET /api/v1/portfolio/allocation-plans/{plan_id}/reviews?target_key=...`：返回两个维度各自最新记录 `latest` 和倒序历史 `items`。默认 20 条、最多 100 条，使用 `next_before_id` 作为下一页 `before_id`。`latest` 不随历史翻页倒退。
- `decision` 为 `maintain_plan`、`wait`、`data_required` 或 `pause`，均是研究记录。缺少记录不默认允许交易；维持计划不代表立即买入。理由、证据/缺口、下一步条件和最迟复核时间不得留空；时区统一存 UTC，页面按本机时区显示。
- 相同请求键、相同内容重试只产生一条记录，包括到期后的重试；请求键内容冲突、计划版本或本轨前置记录过期返回 409。另一个维度的更新不会覆盖本轨。并发写入串行化并有唯一修订号保护。
- 最新记录动态标记 `active`（待按条件复核）、`due`、`plan_changed` 或 `plan_inactive`。到期不自动续期或强制买入；重新判断必须追加记录。记录冻结原目标、原计划版本、前置记录 ID 和服务器时间，目标改名/删除后旧记录仍可经接口查询。
- `authority=manual_unverified`：证据是人工提供的文字与来源/时间，不自动抓取或核验。目前不从聊天、投资档案、模型研报自动生成复核，也不监控条件是否触发；这是审计基础，不是新择时算法。
- 复核不写持仓、成交、现金、委托、共享预算或计划权重，不改变配置上限或绕过资金门禁。页面展开后才读取，明确点击才提交；失败重试保留请求键，切换资产/计划隔离旧请求和草稿。
- 当日配置状态目标新增 `research_reviews`；已启用 `include_in_reports` 的计划将当前复核附入既有中英文简报。旧客户端可忽略新增字段。历史日期重新估值不附入今天的复核，历史报告已冻结内容不追溯更新。

数据库新增 `portfolio_allocation_reviews` 表，由现有 `Base.metadata.create_all` 创建，不改写旧表或真实账本。升级前备份数据库并在隔离环境验收。回滚代码时保留新表和记录；旧版本忽略新表，也不再呈现到期提醒，不应继续把旧判断当作有效信号。禁止为了回滚删除投资记录。

本机测试不能替代 Windows 正式服务的模型连通性、真实新闻采集、券商账单与档案一致性验收；未验证上述项目时，不应宣称生产闭环通过。

### 期初持仓与资金分层

持仓页的“持仓基线与资金分层”面板用于已有资产开户初始化，不把已有持仓伪造成新买入或入金。

- 只允许空账本建立一份不可覆盖的期初基线。先填写已结束的一天、各标的股数、已有单位成本及明确核实的账面现金；成本和金额均按账户基础币种，市场沿用账户设置。当前版本不支持混合市场或多币种期初，请分账户录入。
- 先预览并核对券商分项市值、持仓总市值、账户净值。差额单独显示，不分摊到证券，也不将“净值减市值”直接视作现金。现金未知可预览，必须明确确认账面现金后才能提交；0 必须是真实确认的零余额。报送市值仅用于对账，不充当实时行情。
- 提交需要 `confirmed: true` 和预览内容对应的 `preview_token`。相同内容重复确认幂等；并发确认只创建一份基线。若已有交易、现金或公司行动流水则拒绝，需人工对账。基线确认后只能录入日期严格晚于基线的事件，包含 CSV 批量导入；不应将已包含在基线中的历史成交再导入。
- FIFO 将每个期初标的作为一个平均成本合并批次，不能还原券商的历史批次或期初前已实现收益。后续成交继续按已有 FIFO / 移动均价流程回放；查询基线之前的持仓历史会报错，而不是展示零资产。已有基线的账户不能直接修改市场或计价币种。
- 单独录入已结算现金、可买入的自有现金、计划追加额及预计日期；不包含融资购买力，也不生成入金流水。真正到账后需录入现金流水并重新确认。采用两种已确认现金的较小值，且跨日或交易 / 现金 / 公司行动等账本变化后失效。日期按应用本地日期；不是自动推导的券商结算状态。

新增接口（路径前缀 `/api/v1/portfolio`）：

| 方法 / 路径 | 行为 |
| --- | --- |
| `POST /accounts/{account_id}/opening-balance/preview` | 只读预览、差额及确认令牌 |
| `POST /accounts/{account_id}/opening-balance` | 用户明确确认后建立期初 |
| `POST /accounts/{account_id}/funding` | 保存一条资金核实记录，不改变账面现金 |
| `GET /accounts/{account_id}/state?as_of=YYYY-MM-DD` | 期初与资金状态；旧日期可查看当日记录，不等于严格历史时点回测 |

配置返回三个不同层次：`allocation_cap` 为目标及批次上限，旧字段 `recommended_amount` 仍为账面预算约束后的规划上限；新增 `funded_amount` 为已核实现金可以覆盖的加仓上限，`null` 表示未核实，而不是零现金。`confirmed_cash` 是扣除计划预留后的确认资金上限。所有金额依旧不是市场择时指令，执行前还须预留费用并核实行情。

确认资金同时受账面原币现金限制，只汇总同市场、对应原币账户；不假设即时换汇或跨市场划转。任何范围内账户缺少有效资金确认、现金汇率不可核验、账本未确认完整时，此次现金覆盖保持未知；不同目标共享预算，不能重复使用现金。无明确市场的目标不输出已确认现金覆盖金额。`funding_accounts` 保留各账户原币计划追加信息，未来资金不会抬高任何现金上限。

页面的分组查看只汇总当前计划选中的目标，不保存另一个配置计划，不重新分配现金。例如“美股＋黄金”是100万元总计划中的30万元目标小计，不是额外再加30万元；当前金额缺失时，小计也标记未知。日报的账面预算与现金覆盖采用同一状态返回值，中英文均注明未知现金不能作为可执行依据。

本阶段不对接券商下单，也不包含致富原始成交 CSV 专用解析、精确结算日自动计算或盘中做 T 信号；这些仍需样本与后续实现。

### 配置计划接口

- `POST /api/v1/portfolio/allocation-plans`：创建计划。
- `GET /api/v1/portfolio/allocation-plans`：列出计划。
- `GET /api/v1/portfolio/allocation-plans/{plan_id}`：读取计划及目标。
- `PUT /api/v1/portfolio/allocation-plans/{plan_id}`：整体替换目标并递增版本。
- `DELETE /api/v1/portfolio/allocation-plans/{plan_id}`：停用计划，不删除历史记录。
- `GET /api/v1/portfolio/allocation-plans/{plan_id}/status`：计算配置状态。

状态接口支持与计划一致的 `account_id`、`as_of`、`cost_method` 和 `include_realtime`。跨币种计算复用持仓模块的汇率缓存；缺少汇率时会标记 `partial`，不得把结果当作精确配置建议。计划新字段都有安全默认值，旧客户端可继续读取；旧计划升级后需要完整性确认才能生成持仓增减金额。

## 持仓页面与每日简报

持仓页面新增“目标配置”区域，可创建、编辑计划，录入目标、上下限、单批金额和手工余额，查看当前占比、缺口、预算及等待条件。该区域始终按计划绑定范围计算，不跟随页面上方的临时账户筛选。首次使用缓存行情，点击“更新配置行情”尝试获取实时价格；最近收盘参考价仍可计算配置估算，真正缺失、异常或错过最新完整交易日的数据才暂停对应标的金额。

将 `include_in_reports` 设为 `true`（页面勾选“加入每日简报”）后，配置提醒加入 `run_market_review` 的 A 股、美股及多市场日报，并沿用现有报告接收人。默认关闭；余额会随启用后的报告发送。配置内容在市场分析结束后确定性生成，正文、文件、合并通知、结构化 Web 视图和历史记录共用同一结果，不由 LLM 改写金额。

纯上下文预热（同时关闭 `save_report_file` 和 `persist_history`）不读取个人配置。一个计划评估失败会显示“本次不提供金额”，不阻断市场正文。历史报告保存计划修订号及当次配置快照，可回看当时金额与数据条件；这不代表已建立策略收益归因或完整计划版本审计。

多个计划分别计算预算，可能共用账户现金；不同计划的金额不能叠加执行。推荐只启用实际采用的方案，替代方案保留为不发送的草案。

## 100万元方案示例

下面的示例与个人持仓数据分离，仅演示如何录入目标。存款和债券余额未知时保留 `current_amount: null`，系统会要求补充，而不会按零持仓建议一次性买满。

```json
{
  "name": "100万长期目标配置",
  "base_currency": "CNY",
  "target_total_value": 1000000,
  "account_id": null,
  "ledger_complete": false,
  "cash_reserve_amount": 100000,
  "include_in_reports": false,
  "targets": [
    {"key":"liquidity","name":"流动资金","source":"cash","policy":"rebalance","target_pct":10,"min_pct":8,"max_pct":12,"batch_amount":20000},
    {"key":"fixed_income","name":"稳健固收","source":"manual","policy":"rebalance","target_pct":35,"min_pct":30,"max_pct":40,"batch_amount":50000,"current_amount":null},
    {"key":"a_dividend_low_vol","name":"A股红利低波","source":"position","policy":"buy_only","market":"cn","symbols":["512890"],"target_pct":15,"min_pct":12,"max_pct":18,"batch_amount":30000},
    {"key":"a_broad","name":"A股宽基","source":"position","policy":"buy_only","market":"cn","symbols":["510300"],"target_pct":10,"min_pct":8,"max_pct":12,"batch_amount":20000},
    {"key":"qqqm","name":"纳斯达克100","source":"position","policy":"buy_only","market":"us","symbols":["QQQM"],"target_pct":14,"min_pct":11,"max_pct":17,"batch_amount":23000},
    {"key":"sp500","name":"标普500","source":"position","policy":"buy_only","market":"us","symbols":["VOO","IVV"],"target_pct":8,"min_pct":6,"max_pct":10,"batch_amount":13000},
    {"key":"euv","name":"半导体设备卫星仓","source":"position","policy":"rebalance","market":"us","symbols":["EUV"],"target_pct":2,"max_pct":3,"batch_amount":5000},
    {"key":"dram","name":"存储卫星仓","source":"position","policy":"rebalance","market":"us","symbols":["DRAM"],"target_pct":1,"max_pct":2,"batch_amount":5000},
    {"key":"gold","name":"黄金","source":"position","policy":"buy_only","market":"cn","symbols":["518880"],"target_pct":5,"min_pct":4,"max_pct":6,"batch_amount":10000}
  ]
}
```

场外基金 `021514` 与 `512890` 不应放在同一个匹配目标中。前者若尚未录入持仓账本，会继续作为手工资产管理；录入后会出现在 `unassigned_positions`，等待结合赎回费、净值和退出条件单独处理。

## 新增战术仓测算 / Tactical lot preview

持仓页新增独立测算卡，API 为 `POST /api/v1/portfolio/tactical-research/preview`。原战略配置引擎继续计算目标缺口，不移除其预算保护；战术预览不读取目标缺口或原仓成本，所以达到目标比例不会直接阻断战术研究。这不是自动趋势择时引擎，也不修改战略比例。

- 用户显式填写：扣除生活备用金、核心长期预算、其他订单/方案后同一批共用的已结算美元现金与核实时间、每笔新增本金的损失承受极限，以及最多十笔候选的新增本金、计划损失比例、双边所有费用/价差/滑点估计、依据和失效条件。不会默认填入历史现金、止损比例或券商购买力。
- 现金时间必须含时区，超过 24 小时或未来时间要求复核；即使时点有效，也只是用户输入，不是券商核验。
- 合计现金占用 = 各笔新增本金 + 各笔全往返成本预留，保守地提前留出退出费用。同一笔可用现金不能给每个标的单独重复分配；未知费用保留未知，不当作 0。多个页面/多次预览不会互相预留额度，实际执行前仍需通过现有资金账本核对。
- 单笔计划损失 = 新增本金 × 逻辑失效计划损失比例 + 往返成本；承受金额 = 该笔新增本金 × 承受极限。40% 是用户可能选择的极端承受水平，不是默认止损，不作用于原底仓，更不保证实际亏损封顶。逻辑失效可更早退出，跳空和滑点可能超过计划。
- 返回 `scenario_only` 仅表示资金算术通过；全部响应 `executable=false`，不核验实时行情、账户规则、组合集中度，不给股数或买卖指令，不写账本、预算、成交、现金确认或订单。失败返回 `needs_revision` 与明确原因。修改输入后清除旧结果，过时异步结果不展示。
- 新增仓和旧底仓必须在真实成交确认后按批次区分。均价下降不等于净收益，单纯预览不能宣称已降本。战术策略的实盘信号与绩效验证仍是后续工作，不把该计算器宣称为自动买点推荐。

English: The stateless tactical preview is separate from strategic target-gap allocation. Inputs are user-reported free settled cash, timestamp, new-lot capital, planned loss, tolerance, all-in costs and thesis/invalidation. All lots share one cash pool; unknown costs remain unknown. Tolerance is measured on each NEW lot, never the original core or total account, and is not a default stop or a guaranteed loss cap. Every response is non-executable. No quotes, broker validation, concentration evaluation, reservations or ledger writes occur. Editing inputs invalidates results.

API 为追加接口，无数据库变更、无新环境配置；前后端须一起部署。回滚仅移除此接口和页面卡，不更改持仓/预算。此专题无独立英文文档，本节及网页标签同步提供英文语义。

## 数据边界

- 没有有效价格、报价时间未知、异常未来报价或严重过期时，该目标返回 `review`，0 金额表示待核实，并不代表判断应买 0 元。
- `price_timestamp` 保存来源实际报价时间，`price_fetched_at` 保存抓取时间，`price_date` 按交易所时区取日期，不能互相替代。实时 TTL（默认 600 秒）不放宽；但配置估算另外识别最近完整交易日的收盘日线，或该交易日收盘前最后一分钟至当日盘后的带时间报价。盘中旧报价不能冒充收盘价。
- 收盘参考必须通过已有交易所日历验证，支持周末、假期和提前收市；下一交易日开市前及盘中可继续用最近完整日收盘值估算，新的交易日收盘后旧值失效。日历不可用或日期超出范围时不放宽。日线不能提前使用尚未收盘当日数据。
- 使用收盘参考或日线汇率的目标返回 `is_estimate=true` 和包含原始日期的 `reference_notes`；Web 与中英文日报明确标注“估算参考”，仍计算仓位、缺口和现金约束下的本批上限，不将它解释为现在可成交的指令。
- ETF 的 `tencent` / `akshare_sina` 路由分别调用腾讯 / 新浪直连接口；`akshare_em` 与 `efinance` 仍依赖东方财富。腾讯、新浪保留原始日期时间；Yahoo 使用同一原始记录中的 `regularMarketPrice` 与 `regularMarketTime`，不能拼接其他价格的时间。无法核验时点的兜底源仅提供参考价。
- 原持仓会计估值的汇率时效标记保持严格，不改变历史盈亏计算。配置估算独立读取原币持仓市值及各币种现金，不沿用账户历史盈亏的汇率总标记；某一持仓缺汇率不会挡住不依赖它的人民币资产。
- 配置日线汇率允许评估日或前一个工作日（周末及周一可用周五），且数据源不能自身标记异常；更长的假期缺口、未来日期、无效值或缺失汇率仍需刷新。不使用 1:1 兜底生成金额。所有日线换算都标注估算，不是券商实时换汇报价；源日期不重写。
- 如果现金自身需要的汇率缺失，因无法确认共享现金预算及预留，仍暂停所有新增金额；已有持仓的独立可核验缺口可继续展示。未知余额仍不得视为零，完整性确认、目标缺口、批次上限与现金预留规则不变。
- 计划百分比必须合计为100%，同一标的不能同时属于两个目标。
- 修改计划会递增 `version`，用于识别当前规则的修订号；当前版本只保存最新内容，不提供完整的历史审计表。
- 当前版本未实现ETF成分穿透、市场择时或概率信号融合；这些属于后续阶段。

## 升级与回滚

数据库启动时自动为旧计划表追加范围、完整性确认、现金预留和日报开关四列，幂等执行，不改动交易账本。非 SQLite 数据库仍需按部署环境审查 DDL 权限。回滚应用代码可保留这些追加列和历史报告数据；回滚后旧版不具备新增预算与时效约束，建议暂停使用旧版金额输出。

行情时效修复不增加数据库列；持仓 API 只追加可空的 `price_timestamp` / `price_fetched_at`，原字段保留。回退该修复会重新失去时间校验和 ETF 独立路由，届时应暂停配置金额提醒，不能将旧版“实时价”标签作为可执行依据。

分层估算追加目标状态 `is_estimate` / `reference_notes`，不改数据库或持仓账本。后端与 Web 应配套更新，否则旧客户端可能不展示估算标签。仅回退分层估算补丁会恢复严格拦截；完整回退旧行情修复仍需按上一段暂停金额提醒。专题文档目前仅中文；英文页面和报告标签已同步。

期初与资金分层升级新增 `portfolio_opening_balances` / `portfolio_funding_snapshots` 两张表，通过现有建表流程幂等创建，不改写已有流水，不新增环境变量。API 仅追加字段和接口；前后端应配套部署，否则旧页面仍可能只展示账面预算。升级前备份数据库。**若已建立期初基线，禁止直接回滚后继续用旧版计算持仓**：旧版不认识基线，会漏算已有资产。回滚前暂停配置提醒和持仓功能，保留备份及新表；恢复新版本或完成受控账本迁移后再启用，不删除基线表作为回滚办法。
