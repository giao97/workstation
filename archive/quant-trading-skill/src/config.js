require('dotenv').config({ path: require('path').join(__dirname, '..', '.env') });

const path = require('path');

module.exports = {
  // 数据目录
  dataDir: process.env.DATA_DIR || path.join(__dirname, '..', 'data', 'daily'),
  reportDir: process.env.REPORT_DIR || path.join(__dirname, '..', 'data', 'reports'),

  // A股关注列表
  aShareWatchlist: (process.env.A_SHARE_WATCHLIST || '000001.SZ,000002.SZ,600519.SS,002594.SZ,300750.SZ').split(',').map(s => s.trim()),

  // 美股关注列表
  usStockWatchlist: (process.env.US_STOCK_WATCHLIST || 'AAPL,TSLA,NVDA,MSFT,GOOGL').split(',').map(s => s.trim()),

  // 新闻源配置
  newsSources: {
    eastmoney: 'https://finance.eastmoney.com/a/cywjh.html', // 东方财富要闻
    sinaFinance: 'https://finance.sina.com.cn/stock/',      // 新浪财经
    cnbc: 'https://www.cnbc.com/id/100003114/device/rss/rss.html',
    reuters: 'https://www.reutersagency.com/feed/?best-topics=business-finance'
  },

  // 政策源配置
  policySources: {
    csrc: 'http://www.csrc.gov.cn/csrc/c100028/common_list.shtml', // 证监会
    pbc: 'http://www.pbc.gov.cn/zhengcehuobisi/11140/index.html',  // 央行货币政策
    sse: 'http://www.sse.com.cn/lawsRegulations/lawsAndRegulations/news/', // 上交所
    szse: 'https://www.szse.cn/lawsrules/rule/new/',                // 深交所
    nasdaq: 'https://www.nasdaq.com/news-and-insights'
  },

  // 技术指标参数
  indicators: {
    rsiPeriod: parseInt(process.env.RSI_PERIOD || '14'),
    rsiOverbought: parseInt(process.env.RSI_OVERBOUGHT || '70'),
    rsiOversold: parseInt(process.env.RSI_OVERSOLD || '30'),
    maShort: parseInt(process.env.MA_SHORT || '5'),
    maMedium: parseInt(process.env.MA_MEDIUM || '20'),
    maLong: parseInt(process.env.MA_LONG || '60'),
    macdFast: 12,
    macdSlow: 26,
    macdSignal: 9,
    bollingerPeriod: 20,
    bollingerStdDev: 2,
    atrPeriod: 14,
    stopLossAtrMultiplier: parseFloat(process.env.STOP_LOSS_ATR_MULTIPLIER || '2.0'),
    takeProfitAtrMultiplier: parseFloat(process.env.TAKE_PROFIT_ATR_MULTIPLIER || '3.0')
  },

  // 提醒配置
  email: {
    host: process.env.EMAIL_HOST,
    port: parseInt(process.env.EMAIL_PORT || '465'),
    user: process.env.EMAIL_USER,
    pass: process.env.EMAIL_PASS,
    to: process.env.EMAIL_TO
  },

  // API Keys
  tushareToken: process.env.TUSHARE_TOKEN,
  newsApiKey: process.env.NEWSAPI_KEY
};
