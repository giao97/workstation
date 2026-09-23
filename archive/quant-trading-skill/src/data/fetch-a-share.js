const axios = require('axios');
const yahooFinance = require('yahoo-finance2').default;

/**
 * A股数据抓取器
 * 策略: 优先使用 Yahoo Finance (支持 A股后缀 .SS/.SZ)
 * 备用: 东方财富/新浪 API 获取实时行情
 */
class AShareFetcher {
  constructor() {
    this.baseUrl = 'https://push2.eastmoney.com/api/qt/stock/get';
  }

  /**
   * 将 A股代码转换为 Yahoo Finance 格式
   * 600519.SS, 000001.SZ, 300750.SZ
   */
  normalizeSymbol(symbol) {
    if (symbol.endsWith('.SS') || symbol.endsWith('.SZ')) return symbol;
    if (symbol.startsWith('6')) return `${symbol}.SS`;
    return `${symbol}.SZ`;
  }

  async fetchHistorical(symbol, period = '6mo', interval = '1d') {
    const yahooSymbol = this.normalizeSymbol(symbol);
    try {
      const end = new Date();
      const start = new Date();
      if (period === '1mo') start.setMonth(start.getMonth() - 1);
      else if (period === '3mo') start.setMonth(start.getMonth() - 3);
      else if (period === '6mo') start.setMonth(start.getMonth() - 6);
      else if (period === '1y') start.setFullYear(start.getFullYear() - 1);

      const queryOptions = { period1: start, period2: end, interval };
      const result = await yahooFinance.chart(yahooSymbol, queryOptions);

      return result.map(d => ({
        date: d.date.toISOString().split('T')[0],
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
        volume: d.volume,
        adjClose: d.adjClose || d.close
      }));
    } catch (err) {
      console.error(`[AShare] Yahoo historical failed for ${symbol}, trying EastMoney...`);
      return this.fetchEastMoneyHistorical(symbol);
    }
  }

  async fetchEastMoneyHistorical(symbol) {
    try {
      // 东方财富 K线 API
      const secid = symbol.startsWith('6') ? `1.${symbol}` : `0.${symbol}`;
      const url = `https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=${secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=0&end=20500101&lmt=360`;
      const resp = await axios.get(url, { timeout: 15000 });
      const klines = resp.data.data?.klines || [];
      return klines.map(line => {
        const [date, open, close, high, low, volume] = line.split(',');
        return { date, open: +open, close: +close, high: +high, low: +low, volume: +volume };
      });
    } catch (err) {
      console.error(`[AShare] EastMoney historical failed for ${symbol}:`, err.message);
      return null;
    }
  }

  async fetchQuote(symbol) {
    const yahooSymbol = this.normalizeSymbol(symbol);
    try {
      const quote = await yahooFinance.quote(yahooSymbol);
      return {
        symbol,
        price: quote.regularMarketPrice,
        change: quote.regularMarketChange,
        changePercent: quote.regularMarketChangePercent,
        volume: quote.regularMarketVolume,
        marketCap: quote.marketCap,
        pe: quote.trailingPE,
        pb: quote.priceToBook,
        eps: quote.epsTrailingTwelveMonths,
        fiftyTwoWeekHigh: quote.fiftyTwoWeekHigh,
        fiftyTwoWeekLow: quote.fiftyTwoWeekLow,
        timestamp: new Date().toISOString()
      };
    } catch (err) {
      return this.fetchEastMoneyQuote(symbol);
    }
  }

  async fetchEastMoneyQuote(symbol) {
    try {
      const secid = symbol.startsWith('6') ? `1.${symbol}` : `0.${symbol}`;
      const url = `https://push2.eastmoney.com/api/qt/stock/get?secid=${secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f162,f163,f164,f165,f170,f171,f177,f183,f184,f185,f186,f187,f188`;
      const resp = await axios.get(url, { timeout: 15000 });
      const d = resp.data.data;
      if (!d) return null;
      return {
        symbol,
        name: d.f58,
        price: d.f43 / 100,
        open: d.f46 / 100,
        high: d.f44 / 100,
        low: d.f45 / 100,
        prevClose: d.f60 / 100,
        change: (d.f43 - d.f60) / 100,
        changePercent: d.f170 / 100,
        volume: d.f47,
        amount: d.f48,
        pe: d.f162 / 100,
        pb: d.f163 / 100,
        marketCap: d.f20,
        turnoverRate: d.f168 / 100,
        timestamp: new Date().toISOString()
      };
    } catch (err) {
      console.error(`[AShare] Quote failed for ${symbol}:`, err.message);
      return null;
    }
  }
}

module.exports = AShareFetcher;

