# 量化投研工作区

本工作区只保留一条正式开发和运行主线：

## 唯一主系统

`C:\Users\PC\workStation\daily_stock_analysis`

该项目负责每日市场与个股新闻、基本面、技术分析、条件式买卖参考、历史结果评估、报告、Web/桌面端、API、调度和通知。后续正式功能、配置和运行入口全部以该项目为准。

常用入口：

```powershell
cd C:\Users\PC\workStation\daily_stock_analysis
python main.py --dry-run
python main.py --stocks 600519,hk00700,AAPL
python main.py --market-review
python main.py --serve-only
```

详细使用方法见：

- `daily_stock_analysis\README.md`
- `daily_stock_analysis\docs\full-guide.md`
- `markDown\量化系统方案.md`

## 归档项目

旧的 `quant-trading-py` 和 `quant-trading-skill` 已停止作为独立开发线。它们完整保存在 `archive` 目录，仅用于历史数据、旧报告、测试案例和迁移参考，不应再单独配置、运行或增加功能。

如需迁移旧能力，应先确认主系统是否已经覆盖，再以最小改动迁入 `daily_stock_analysis` 并补充测试。不得从归档项目复制出新的平行数据管线、信号引擎或报告系统。

## 系统边界

- 系统用于投研与决策辅助，不自动下单。
- 输出应包含证据、数据时点、基本面、估值、历史统计、概率预测和条件式价格区间。
- 财务指标、估值和历史统计由确定性代码计算；LLM 负责归纳和解释。
- 完整长期边界保存在 `INVESTMENT_PROFILE.md`。
