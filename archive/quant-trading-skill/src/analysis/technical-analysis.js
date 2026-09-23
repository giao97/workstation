/**
 * 技术分析引擎
 * 实现: SMA, EMA, RSI, MACD, 布林带, KDJ, ATR, OBV, 成交量均线
 */
class TechnicalAnalysis {
  constructor(config) {
    this.cfg = config;
  }

  sma(data, period) {
    if (data.length < period) return new Array(data.length).fill(null);
    const result = new Array(period - 1).fill(null);
    for (let i = period - 1; i < data.length; i++) {
      const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0);
      result.push(sum / period);
    }
    return result;
  }

  ema(data, period) {
    if (data.length < period) return new Array(data.length).fill(null);
    const k = 2 / (period + 1);
    const result = [null];
    let prevEma = data[0];
    for (let i = 1; i < data.length; i++) {
      prevEma = data[i] * k + prevEma * (1 - k);
      result.push(prevEma);
    }
    // 前 period-1 个置为 null
    for (let i = 0; i < period - 1; i++) result[i] = null;
    return result;
  }

  rsi(closes, period = 14) {
    if (closes.length < period + 1) return new Array(closes.length).fill(null);
    const result = new Array(period).fill(null);
    let gain = 0, loss = 0;
    for (let i = 1; i <= period; i++) {
      const diff = closes[i] - closes[i - 1];
      if (diff > 0) gain += diff;
      else loss -= diff;
    }
    let avgGain = gain / period;
    let avgLoss = loss / period;
    for (let i = period; i < closes.length; i++) {
      const diff = closes[i] - closes[i - 1];
      avgGain = ((avgGain * (period - 1)) + (diff > 0 ? diff : 0)) / period;
      avgLoss = ((avgLoss * (period - 1)) + (diff < 0 ? -diff : 0)) / period;
      const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
      result.push(avgLoss === 0 ? 100 : 100 - (100 / (1 + rs)));
    }
    return result;
  }

  macd(closes, fast = 12, slow = 26, signal = 9) {
    const emaFast = this.ema(closes, fast);
    const emaSlow = this.ema(closes, slow);
    const macdLine = emaFast.map((f, i) => (f === null || emaSlow[i] === null) ? null : f - emaSlow[i]);
    const validMacd = macdLine.filter(v => v !== null);
    const signalLine = this.ema(validMacd, signal);
    // 对齐
    const sl = new Array(macdLine.length - validMacd.length).fill(null).concat(signalLine);
    const histogram = macdLine.map((m, i) => (m === null || sl[i] === null) ? null : m - sl[i]);
    return { macdLine, signalLine: sl, histogram };
  }

  bollinger(closes, period = 20, stdDev = 2) {
    const middle = this.sma(closes, period);
    const upper = [];
    const lower = [];
    for (let i = 0; i < closes.length; i++) {
      if (middle[i] === null) {
        upper.push(null);
        lower.push(null);
        continue;
      }
      const slice = closes.slice(i - period + 1, i + 1);
      const mean = middle[i];
      const variance = slice.reduce((sum, val) => sum + (val - mean) ** 2, 0) / period;
      const sd = Math.sqrt(variance);
      upper.push(mean + stdDev * sd);
      lower.push(mean - stdDev * sd);
    }
    return { upper, middle, lower };
  }

  kdj(highs, lows, closes, n = 9, m1 = 3, m2 = 3) {
    const rsv = [];
    for (let i = 0; i < closes.length; i++) {
      if (i < n - 1) { rsv.push(null); continue; }
      const periodHighs = highs.slice(i - n + 1, i + 1);
      const periodLows = lows.slice(i - n + 1, i + 1);
      const highestHigh = Math.max(...periodHighs);
      const lowestLow = Math.min(...periodLows);
      if (highestHigh === lowestLow) rsv.push(50);
      else rsv.push((closes[i] - lowestLow) / (highestHigh - lowestLow) * 100);
    }
    const k = [rsv[n - 1] || 50];
    const d = [k[0]];
    for (let i = n; i < rsv.length; i++) {
      const prevK = k[k.length - 1];
      const prevD = d[d.length - 1];
      k.push((2 * prevK + rsv[i]) / 3);
      d.push((2 * prevD + k[k.length - 1]) / 3);
    }
    const j = k.map((kv, i) => 3 * kv - 2 * d[i]);
    // 补齐前面
    const pad = new Array(n - 1).fill(null);
    return { k: pad.concat(k), d: pad.concat(d), j: pad.concat(j) };
  }

  atr(highs, lows, closes, period = 14) {
    if (highs.length < period + 1) return new Array(highs.length).fill(null);
    const tr = [highs[0] - lows[0]];
    for (let i = 1; i < highs.length; i++) {
      tr.push(Math.max(
        highs[i] - lows[i],
        Math.abs(highs[i] - closes[i - 1]),
        Math.abs(lows[i] - closes[i - 1])
      ));
    }
    const result = new Array(period).fill(null);
    let atrVal = tr.slice(0, period).reduce((a, b) => a + b, 0) / period;
    result.push(atrVal);
    for (let i = period + 1; i < tr.length; i++) {
      atrVal = (atrVal * (period - 1) + tr[i]) / period;
      result.push(atrVal);
    }
    return result;
  }

  obv(closes, volumes) {
    const obv = [volumes[0]];
    for (let i = 1; i < closes.length; i++) {
      if (closes[i] > closes[i - 1]) obv.push(obv[obv.length - 1] + volumes[i]);
      else if (closes[i] < closes[i - 1]) obv.push(obv[obv.length - 1] - volumes[i]);
      else obv.push(obv[obv.length - 1]);
    }
    return obv;
  }

  volumeMA(volumes, period = 20) {
    return this.sma(volumes, period);
  }

  analyze(ohlcv) {
    const closes = ohlcv.map(d => d.close);
    const highs = ohlcv.map(d => d.high);
    const lows = ohlcv.map(d => d.low);
    const volumes = ohlcv.map(d => d.volume);

    const cfg = this.cfg;
    const ma5 = this.sma(closes, cfg.maShort);
    const ma20 = this.sma(closes, cfg.maMedium);
    const ma60 = this.sma(closes, cfg.maLong);
    const ema12 = this.ema(closes, cfg.macdFast);
    const ema26 = this.ema(closes, cfg.macdSlow);
    const rsi14 = this.rsi(closes, cfg.rsiPeriod);
    const macdResult = this.macd(closes, cfg.macdFast, cfg.macdSlow, cfg.macdSignal);
    const bb = this.bollinger(closes, cfg.bollingerPeriod, cfg.bollingerStdDev);
    const kdjResult = this.kdj(highs, lows, closes);
    const atr14 = this.atr(highs, lows, closes, cfg.atrPeriod);
    const obvResult = this.obv(closes, volumes);
    const volMA20 = this.volumeMA(volumes, 20);

    const lastIdx = closes.length - 1;
    const prevIdx = lastIdx - 1;

    return {
      latest: {
        close: closes[lastIdx],
        ma5: ma5[lastIdx],
        ma20: ma20[lastIdx],
        ma60: ma60[lastIdx],
        rsi: rsi14[lastIdx],
        macd: macdResult.macdLine[lastIdx],
        macdSignal: macdResult.signalLine[lastIdx],
        bbUpper: bb.upper[lastIdx],
        bbMiddle: bb.middle[lastIdx],
        bbLower: bb.lower[lastIdx],
        k: kdjResult.k[lastIdx],
        d: kdjResult.d[lastIdx],
        j: kdjResult.j[lastIdx],
        atr: atr14[lastIdx],
        obv: obvResult[lastIdx],
        volumeMA: volMA20[lastIdx],
        volume: volumes[lastIdx]
      },
      prev: {
        close: closes[prevIdx],
        macd: macdResult.macdLine[prevIdx],
        macdSignal: macdResult.signalLine[prevIdx],
        k: kdjResult.k[prevIdx],
        d: kdjResult.d[prevIdx],
        rsi: rsi14[prevIdx]
      },
      trend: {
        ma5, ma20, ma60,
        rsi: rsi14,
        macd: macdResult,
        bollinger: bb,
        kdj: kdjResult,
        atr: atr14,
        obv: obvResult,
        volumeMA: volMA20
      }
    };
  }
}

module.exports = TechnicalAnalysis;

