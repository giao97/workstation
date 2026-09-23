const TechnicalAnalysis = require('./analysis/technical-analysis');
const FundamentalAnalysis = require('./analysis/fundamental-analysis');
const SentimentAnalysis = require('./analysis/sentiment-analysis');
const SignalEngine = require('./analysis/signal-engine');
const config = require('./config');

console.log('=== 量化交易系统模块测试 ===\n');

// 1. 测试技术指标
console.log('1. 测试技术指标计算...');
const tech = new TechnicalAnalysis(config.indicators);
const mockData = [];
let price = 100;
for (let i = 0; i < 100; i++) {
  const change = (Math.random() - 0.48) * 5;
  price += change;
  const open = price - Math.random() * 2;
  const close = price;
  const high = Math.max(open, close) + Math.random() * 2;
  const low = Math.min(open, close) - Math.random() * 2;
  mockData.push({
    date: `2024-01-${String(i+1).padStart(2,'0')}`,
    open, high, low, close,
    volume: Math.floor(Math.random() * 1000000 + 500000)
  });
}
const techResult = tech.analyze(mockData);
console.log('  ? RSI:', techResult.latest.rsi?.toFixed(2));
console.log('  ? MACD:', techResult.latest.macd?.toFixed(3));
console.log('  ? MA20:', techResult.latest.ma20?.toFixed(2));
console.log('  ? ATR:', techResult.latest.atr?.toFixed(3));

// 2. 测试基本面分析
console.log('\n2. 测试基本面分析...');
const fund = new FundamentalAnalysis();
const fundResult = fund.analyze(
  { price: 150, pe: 18, pb: 2.5, forwardPE: 15 },
  { roe: 0.18, revenueGrowth: 0.25, profitMargins: 0.22, debtToEquity: 0.4, recommendationKey: 'buy', targetMeanPrice: 180 }
);
console.log('  ? 评分:', fundResult.totalScore, '/ 100');
console.log('  ? 评级:', fundResult.rating);
console.log('  ? 要点:', fundResult.flags.slice(0, 3).join(' / '));

// 3. 测试情绪分析
console.log('\n3. 测试情绪分析...');
const sentiment = new SentimentAnalysis();
const news = [
  { title: '央行降准释放流动性，利好股市', summary: '' },
  { title: '新能源板块业绩超预期增长', summary: '' },
  { title: '美联储加息预期升温，全球市场承压', summary: '' }
];
const newsAnalysis = sentiment.analyzeNews(news);
const marketSentiment = sentiment.generateMarketSentiment(newsAnalysis, null);
console.log('  ? 新闻1情绪:', newsAnalysis[0].sentiment, `(得分: ${newsAnalysis[0].sentimentScore})`);
console.log('  ? 新闻2情绪:', newsAnalysis[1].sentiment, `(得分: ${newsAnalysis[1].sentimentScore})`);
console.log('  ? 新闻3情绪:', newsAnalysis[2].sentiment, `(得分: ${newsAnalysis[2].sentimentScore})`);
console.log('  ? 市场整体:', marketSentiment.overall, `(综合: ${marketSentiment.combinedScore})`);

// 4. 测试信号引擎
console.log('\n4. 测试信号引擎...');
const signalEngine = new SignalEngine(config.indicators);
const signals = signalEngine.generateSignals(techResult, fundResult, marketSentiment, { price: 150 });
console.log('  ? 综合信号:', signals.overallSignal, `(${signals.overallConfidence})`);
console.log('  ? 理由:', signals.overallReason);
console.log('  ? 止损:', signals.stopLoss);
console.log('  ? 止盈:', signals.takeProfit);
console.log('  ? 盈亏比:', signals.riskRewardRatio);
console.log('  ? 详细信号:');
signals.signals.slice(0, 5).forEach(s => console.log(`     [${s.type}] ${s.source}: ${s.reason}`));

console.log('\n=== 所有模块测试通过 ===');
