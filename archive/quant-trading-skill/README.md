# Quant Trading Skill - A股+美股量化分析系统

## 功能特性

- **行情抓取**: A股(东方财富/Yahoo) + 美股(Yahoo Finance) 实时/历史数据
- **新闻政策解读**: 自动抓取东方财富、新浪财经、CNBC、Reuters、证监会、央行、交易所公告
- **技术面分析**: MA/EMA/RSI/MACD/布林带/KDJ/ATR/OBV/成交量
- **基本面分析**: PE/PB/ROE/ROA/成长性/负债率/分析师共识
- **消息面情绪分析**: 关键词情绪打分，政策影响评估
- **交易信号**: 综合三维度生成买入/卖出/止损/止盈信号
- **TradingView 图表**: 内嵌 Lightweight Charts 专业 K 线图
- **报告生成**: HTML(浏览器打开看图表) / Markdown / JSON
- **提醒通知**: 控制台实时提醒 + 邮件推送(可选)

## 项目结构

```
quant-trading-skill/
├── src/
│   ├── index.js                  # 主入口
│   ├── config.js                 # 配置中心
│   ├── data/
│   │   ├── fetch-a-share.js      # A股数据抓取
│   │   ├── fetch-us-stock.js     # 美股数据抓取
│   │   ├── fetch-news-policy.js  # 新闻政策抓取
│   │   └── storage.js            # 数据存储
│   ├── analysis/
│   │   ├── technical-analysis.js # 技术指标
│   │   ├── fundamental-analysis.js
│   │   ├── sentiment-analysis.js # 情绪分析
│   │   └── signal-engine.js      # 信号引擎
│   ├── report/
│   │   └── report-generator.js   # 报告生成
│   └── alert/
│       └── notifier.js           # 提醒模块
├── data/                         # 数据存储目录
├── .env                          # 环境变量
└── package.json
```

## 快速开始

### 1. 安装依赖
```bash
cd C:\Users\PC\workStation\quant-trading-skill
npm install
```

### 2. 配置环境变量
编辑 `.env` 文件:
```env
# 关注标的 (可自定义)
A_SHARE_WATCHLIST=000001.SZ,000002.SZ,600519.SS,002594.SZ,300750.SZ
US_STOCK_WATCHLIST=AAPL,TSLA,NVDA,MSFT,GOOGL

# 邮件提醒 (可选)
EMAIL_HOST=smtp.qq.com
EMAIL_PORT=465
EMAIL_USER=your_email@qq.com
EMAIL_PASS=your_auth_code
EMAIL_TO=your_email@qq.com
```

### 3. 运行系统
```bash
# 完整模式: 抓取新闻政策 + 分析所有股票 + 生成报告
npm start

# 仅分析股票
npm run analysis

# 仅生成报告 (基于已有数据)
npm run report

# 仅抓取新闻政策
npm run fetch
```

### 4. 查看报告
运行后会在 `data/reports/` 目录生成:
- `report_YYYY-MM-DD.html` - 用浏览器打开，内含 TradingView 风格 K 线图
- `report_YYYY-MM-DD.md` - Markdown 格式
- `report_YYYY-MM-DD.json` - 结构化 JSON 数据

## 数据源

| 市场 | 数据源 | 说明 |
|------|--------|------|
| A股历史 | Yahoo Finance / 东方财富 | 6个月日线 |
| A股实时 | 东方财富 API | 实时行情 |
| 美股 | Yahoo Finance | 历史+实时+基本面 |
| 新闻 | 东方财富/新浪财经/CNBC/Reuters | 财经要闻 |
| 政策 | 证监会/央行/上交所/深交所 | 监管政策 |

## 信号逻辑

系统综合**技术面(50%) + 基本面(30%) + 消息面(20%)**生成信号:

**买入信号示例:**
- MACD 金叉 + RSI < 70 + 价格上破 MA20
- KDJ 低位金叉 + 放量上涨
- 基本面评分 > 75 + 情绪积极

**卖出信号示例:**
- MACD 死叉 + RSI > 80
- 价格跌破布林带下轨 + 放量下跌
- 基本面评分 < 35 + 情绪悲观

**止损/止盈:**
- 止损 = 入场价 - 2 × ATR(14)
- 止盈 = 入场价 + 3 × ATR(14)
- 移动止损 = MA20

## 定时任务 (可选)

使用 Windows 任务计划程序或 node-cron 实现每日自动运行:
```javascript
const cron = require('node-cron');
cron.schedule('0 9 * * 1-5', () => {
  // 每个交易日 9:00 执行
  require('./src/index.js');
});
```

## 注意事项

1. **网络限制**: 部分数据源可能因网络问题抓取失败，系统会自动降级处理
2. **A股代码格式**: 使用 `.SS`(上证) 或 `.SZ`(深证) 后缀，如 `600519.SS`
3. **邮件提醒**: 需配置正确的 SMTP 信息，QQ邮箱使用授权码而非密码
4. **免责声明**: 本系统仅供学习研究，不构成投资建议

## 扩展计划

- [ ] 接入 Tushare Pro 获取更详细的 A股基本面数据
- [ ] 接入 AKShare 获取北向资金/融资融券数据
- [ ] 增加更多策略 (均线突破/趋势跟踪/均值回归)
- [ ] 接入钉钉/企业微信 Webhook 提醒
- [ ] 添加回测模块验证策略有效性
- [ ] 接入 OpenAI API 进行智能新闻摘要
