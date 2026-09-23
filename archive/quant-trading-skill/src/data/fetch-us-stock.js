const yahooFinance = require('yahoo-finance2').default;

class USStockFetcher {
  async fetchHistorical(symbol, period = '6mo', interval = '1d') {
    try {
      const end = new Date();
      const start = new Date();
      if (period === '1mo') start.setMonth(start.getMonth() - 1);
      else if (period === '3mo') start.setMonth(start.getMonth() - 3);
      else if (period === '6mo') start.setMonth(start.getMonth() - 6);
      else if (period === '1y') start.setFullYear(start.getFullYear() - 1);

      const queryOptions = { period1: start, period2: end, interval };
      const result = await yahooFinance.chart(symbol, queryOptions);

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
      console.error(`[USStock] Failed to fetch ${symbol}:`, err.message);
      return null;
    }
  }

  async fetchQuote(symbol) {
    try {
      const quote = await yahooFinance.quote(symbol);
      return {
        symbol,
        price: quote.regularMarketPrice,
        change: quote.regularMarketChange,
        changePercent: quote.regularMarketChangePercent,
        volume: quote.regularMarketVolume,
        marketCap: quote.marketCap,
        pe: quote.trailingPE,
        forwardPE: quote.forwardPE,
        pb: quote.priceToBook,
        eps: quote.epsTrailingTwelveMonths,
        fiftyTwoWeekHigh: quote.fiftyTwoWeekHigh,
        fiftyTwoWeekLow: quote.fiftyTwoWeekLow,
        avgVolume: quote.averageVolume,
        timestamp: new Date().toISOString()
      };
    } catch (err) {
      console.error(`[USStock] Failed to quote ${symbol}:`, err.message);
      return null;
    }
  }

  async fetchFundamentals(symbol) {
    try {
      const fundamentals = await yahooFinance.quoteSummary(symbol, {
        modules: ['financialData', 'defaultKeyStatistics', 'summaryDetail']
      });
      return {
        symbol,
        revenueGrowth: fundamentals.financialData?.revenueGrowth,
        earningsGrowth: fundamentals.financialData?.earningsGrowth,
        profitMargins: fundamentals.financialData?.profitMargins,
        operatingMargins: fundamentals.financialData?.operatingMargins,
        roe: fundamentals.financialData?.returnOnEquity,
        roa: fundamentals.financialData?.returnOnAssets,
        currentRatio: fundamentals.financialData?.currentRatio,
        debtToEquity: fundamentals.financialData?.debtToEquity,
        quickRatio: fundamentals.financialData?.quickRatio,
        targetHighPrice: fundamentals.financialData?.targetHighPrice,
        targetLowPrice: fundamentals.financialData?.targetLowPrice,
        targetMeanPrice: fundamentals.financialData?.targetMeanPrice,
        recommendationKey: fundamentals.financialData?.recommendationKey,
        numberOfAnalystOpinions: fundamentals.financialData?.numberOfAnalystOpinions,
        timestamp: new Date().toISOString()
      };
    } catch (err) {
      console.error(`[USStock] Failed fundamentals ${symbol}:`, err.message);
      return null;
    }
  }
}

module.exports = USStockFetcher;

