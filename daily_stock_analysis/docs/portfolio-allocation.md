# 目标配置与再平衡引擎

目标配置引擎把长期资产配置计划保存为版本化结构，并使用持仓快照、汇率和手工资产余额计算当前占比、目标缺口、超配金额和下一批金额上限。

它只负责确定性的配置计算，不判断市场时机、不连接券商，也不把 `recommended_amount` 当成自动交易指令。实际行动仍需结合当日估值、走势、重大消息和数据质量重新确认。

## 三种当前金额来源

| `source` | 当前金额来源 | 适用场景 |
| --- | --- | --- |
| `position` | 匹配持仓账本中的 `symbols`，按计划币种汇总市值 | ETF、股票、场内基金 |
| `cash` | 汇总持仓账户现金并换算为计划币种 | 流动资金 |
| `manual` | 使用目标中的 `current_amount` | 存款、国债、场外基金等尚未进入账本的资产 |

`manual` 未填写 `current_amount` 时，状态返回 `review`，不会把未知资产误当成零仓位。未被任何目标匹配的持仓会进入 `unassigned_positions`，避免资产静默遗漏。

## 动作策略

| `policy` | 行为 |
| --- | --- |
| `buy_only` | 低于目标时给出下一批金额；高于目标只提示持有，不主动减仓 |
| `rebalance` | 低于目标可增加，高于目标或上限可减少 |
| `hold_only` | 只跟踪，不生成增减建议 |
| `exit_only` | 不新增；高于目标时可给出减仓批次 |

下一批金额等于“目标缺口”和 `batch_amount` 中较小者。该金额是配置层上限，不是当天应该成交的金额。

## API

- `POST /api/v1/portfolio/allocation-plans`：创建计划。
- `GET /api/v1/portfolio/allocation-plans`：列出计划。
- `GET /api/v1/portfolio/allocation-plans/{plan_id}`：读取计划及目标。
- `PUT /api/v1/portfolio/allocation-plans/{plan_id}`：整体替换目标并递增版本。
- `DELETE /api/v1/portfolio/allocation-plans/{plan_id}`：停用计划，不删除历史记录。
- `GET /api/v1/portfolio/allocation-plans/{plan_id}/status`：计算配置状态。

状态接口支持 `account_id`、`as_of`、`cost_method` 和 `include_realtime`。跨币种计算复用持仓模块的汇率缓存；缺少汇率时会标记 `partial`，不得把结果当作精确配置建议。

## 100万元方案示例

下面的示例与个人持仓数据分离，仅演示如何录入目标。存款和债券余额未知时保留 `current_amount: null`，系统会要求补充，而不会按零持仓建议一次性买满。

```json
{
  "name": "100万长期目标配置",
  "base_currency": "CNY",
  "target_total_value": 1000000,
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

## 数据边界

- 持仓没有有效价格时，该目标返回 `review`。
- 汇率缺失或陈旧时，整体状态为 `partial`。
- 计划百分比必须合计为100%，同一标的不能同时属于两个目标。
- 修改计划会递增 `version`，用于识别当前规则的修订号；当前版本只保存最新内容，不提供完整的历史审计表。
- 当前版本未实现ETF成分穿透、市场择时或概率信号融合；这些属于后续阶段。
