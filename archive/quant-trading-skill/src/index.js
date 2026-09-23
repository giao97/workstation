const config = require('./config');
const Storage = require('./data/storage');
const AShareFetcher = require('./data/fetch-a-share');
const USStockFetcher = require('./data/fetch-us-stock');
const NewsPolicyFetcher = require('./data/fetch-news-policy');
const TechnicalAnalysis = require('./analysis/technical-analysis');
const FundamentalAnalysis = require('./analysis/fundamental-analysis');
const SentimentAnalysis = require('./analysis/sentiment-analysis');
const SignalEngine = require('./analysis/signal-engine');
const ReportGenerator = require('./report/report-generator');
const Notifier = require('./alert/notifier');

class QuantTradingSystem {
  constructor() {
    this.storage = new Storage(config.dataDir);
    this.aShareFetcher = new AShareFetcher();
    this.usFetcher = new USStockFetcher();
    this.newsFetcher = new NewsPolicyFetcher();
    this.techAnalysis = new TechnicalAnalysis(config.indicators);
    this.fundAnalysis = new FundamentalAnalysis();
    this.sentimentAnalysis = new SentimentAnalysis();
    this.signalEngine = new SignalEngine(config.indicators);
    this.reportGen = new ReportGenerator(config.reportDir);
    this.notifier = new Notifier(config.email);
    this.marketSentiment = null;
  }

  async run(mode = 'full') {
    console.log('📈 量化交易系统启动...');
    console.log(`模式: ${mode} | 时间: ${new Date().toLocaleString('zh-CN')}`);

    let newsList = [];
    let policyList = [];
    let newsAnalysis = [];
    let policyAnalysis = null;

    // ========== 1. 抓取新闻政策 ==========
    if (mode === 'full' || mode === 'fetch' || mode === 'report') {
      console.log('📰 正在抓取新闻与政策...');
      try {
        newsList = await this.newsFetcher.fetchAllNews();
        policyList = await this.newsFetcher.fetchAllPolicy();
        console.log(`  ✓ 新闻: ${newsList.length} 条 | 政策: ${policyList.length} 条`);

        await this.storage.saveNews(newsList);
        await this.storage.savePolicy(policyList);

        // 情绪分析
        newsAnalysis = this.sentimentAnalysis.analyzeNews(newsList);
        policyAnalysis = this.sentimentAnalysis.analyzePolicyImpact(policyList, 'a-share');
        this.marketSentiment = this.sentimentAnalysis.generateMarketSentiment(newsAnalysis, policyAnalysis);
        console.log(`  ✓ 市场情绪: ${this.marketSentiment.overall} (得分: ${this.marketSentiment.combinedScore})`);
      } catch (err) {
        console.error('  ✗ 新闻政策抓取失败:', err.message);
      }
    }

    // ========== 2. 分析股票 ==========
    if (mode === 'full' || mode === 'analysis' || mode === 'report') {
      const allSymbols = [
        ...config.aShareWatchlist.map(s => ({ symbol: s, market: 'a-share' })),
        ...config.usStockWatchlist.map(s => ({ symbol: s, market: 'us-stock' }))
      ];

      const results = [];
      for (const { symbol, market } of allSymbols) {
        console.log(`\n📊 分析 ${symbol} [${market}]...`);
        try {
          const result = await this.analyzeStock(symbol, market, newsList);
          results.push(result);

          // 存储数据
          await this.storage.saveMarketData(symbol, result);

          // 控制台提醒
          if (result.signals.overallSignal !== 'HOLD') {
            this.notifier.consoleAlert(symbol, result.signals);
          }

          // 邮件提醒 (仅强烈信号)
          if (result.signals.overallSignal.startsWith('STRONG')) {
            await this.notifier.alertTradeSignal(symbol, result.signals, result.quote);
          }
        } catch (err) {
          console.error(`  ✗ ${symbol} 分析失败:`, err.message);
        }
      }

      // ========== 3. 生成报告 ==========
      if (mode === 'full' || mode === 'report') {
        console.log('📋 正在生成报告...');
        try {
          const htmlPath = await this.reportGen.generateHTML(results, newsAnalysis, policyAnalysis, this.marketSentiment);
          const jsonPath = await this.reportGen.generateJSON(results, newsAnalysis, policyAnalysis, this.marketSentiment);
          const mdPath = await this.reportGen.generateMarkdown(results, newsAnalysis, policyAnalysis, this.marketSentiment);
          console.log(`  ✓ HTML 报告: ${htmlPath}`);
          console.log(`  ✓ JSON 数据: ${jsonPath}`);
          console.log(`  ✓ Markdown: ${mdPath}`);

          await this.notifier.alertDailyReport(htmlPath);
        } catch (err) {
          console.error('  ✗ 报告生成失败:', err.message);
        }
      }
    }

    console.log('\n✅ 任务完成!');
  }

  async analyzeStock(symbol, market, newsList = []) {
    // 抓取数据
    let historical, quote, fundamentals;
    if (market === 'a-share') {
      historical = await this.aShareFetcher.fetchHistorical(symbol, '6mo', '1d');
      quote = await this.aShareFetcher.fetchQuote(symbol);
      fundamentals = null;
    } else {
      historical = await this.usFetcher.fetchHistorical(symbol, '6mo', '1d');
      quote = await this.usFetcher.fetchQuote(symbol);
      fundamentals = await this.usFetcher.fetchFundamentals(symbol);
    }

    if (!historical || historical.length < 30) {
      throw new Error('历史数据不足');
    }

    // 技术面分析
    const technical = this.techAnalysis.analyze(historical);

    // 基本面分析
    const fundamental = this.fundAnalysis.analyze(quote, fundamentals);

    // 消息面分析 (个股相关)
    const symbolNews = newsList.filter(n => {
      const text = `${n.title} ${n.summary || ''}`.toLowerCase();
      return text.includes(symbol.toLowerCase()) || text.includes((quote?.name || '').toLowerCase());
    });
    const symbolNewsAnalysis = this.sentimentAnalysis.analyzeNews(symbolNews, symbol);
    const symbolNewsScore = symbolNewsAnalysis.length > 0
      ? symbolNewsAnalysis.reduce((s, n) => s + n.sentimentScore, 0) / symbolNewsAnalysis.length
      : 0;

    // 信号生成
    const sentiment = {
      combinedScore: this.marketSentiment?.combinedScore || 0,
      symbolNewsScore: +symbolNewsScore.toFixed(2)
    };
    const signals = this.signalEngine.generateSignals(technical, fundamental, sentiment, quote);

    return {
      symbol,
      market,
      quote,
      historical: historical.slice(-60),
      technical,
      fundamental,
      signals,
      relatedNews: symbolNewsAnalysis.slice(0, 5)
    };
  }
}

// ========== CLI 入口 ==========
async function main() {
  const args = process.argv.slice(2);
  const modeArg = args.find(a => a.startsWith('--mode='));
  const mode = modeArg ? modeArg.split('=')[1] : 'full';

  const system = new QuantTradingSystem();
  await system.run(mode);
}

main().catch(err => {
  console.error('系统错误:', err);
  process.exit(1);
});

