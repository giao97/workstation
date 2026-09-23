/**
 * 交易信号生成引擎
 * 综合技术面、基本面、消息面三维度生成买卖/止损信号
 */
class SignalEngine {
  constructor(config) {
    this.cfg = config;
  }

  generateSignals(tech, fundamental, sentiment, quote) {
    const signals = [];
    const last = tech.latest;
    const prev = tech.prev;
    const price = quote?.price || last.close;

    // ========== 技术面信号 ==========

    // MACD 金叉/死叉
    if (last.macd !== null && prev.macd !== null && last.macdSignal !== null && prev.macdSignal !== null) {
      if (prev.macd <= prev.macdSignal && last.macd > last.macdSignal) {
        signals.push({ type: 'BUY', source: '技术面', confidence: 'HIGH', reason: 'MACD金叉，动能转强' });
      }
      if (prev.macd >= prev.macdSignal && last.macd < last.macdSignal) {
        signals.push({ type: 'SELL', source: '技术面', confidence: 'HIGH', reason: 'MACD死叉，动能减弱' });
      }
    }

    // RSI 超买超卖
    if (last.rsi !== null) {
      if (last.rsi < this.cfg.rsiOversold) {
        signals.push({ type: 'BUY', source: '技术面', confidence: 'MEDIUM', reason: `RSI ${last.rsi.toFixed(1)} 超卖，可能反弹` });
      }
      if (last.rsi > this.cfg.rsiOverbought) {
        signals.push({ type: 'SELL', source: '技术面', confidence: 'MEDIUM', reason: `RSI ${last.rsi.toFixed(1)} 超买，可能回调` });
      }
    }

    // 均线排列
    if (last.ma5 !== null && last.ma20 !== null && last.ma60 !== null) {
      if (last.ma5 > last.ma20 && last.ma20 > last.ma60 && prev.ma5 <= prev.ma20) {
        signals.push({ type: 'BUY', source: '技术面', confidence: 'HIGH', reason: '多头排列形成，趋势向上' });
      }
      if (last.ma5 < last.ma20 && last.ma20 < last.ma60 && prev.ma5 >= prev.ma20) {
        signals.push({ type: 'SELL', source: '技术面', confidence: 'HIGH', reason: '空头排列形成，趋势向下' });
      }
      if (last.close > last.ma20 && prev.close <= prev.ma20) {
        signals.push({ type: 'BUY', source: '技术面', confidence: 'MEDIUM', reason: '价格上破MA20，短期转强' });
      }
      if (last.close < last.ma20 && prev.close >= prev.ma20) {
        signals.push({ type: 'SELL', source: '技术面', confidence: 'MEDIUM', reason: '价格跌破MA20，短期走弱' });
      }
    }

    // 布林带突破
    if (last.bbUpper !== null && last.bbLower !== null) {
      if (last.close > last.bbUpper) {
        signals.push({ type: 'SELL', source: '技术面', confidence: 'MEDIUM', reason: '价格突破布林带上轨，短期过热' });
      }
      if (last.close < last.bbLower) {
        signals.push({ type: 'BUY', source: '技术面', confidence: 'MEDIUM', reason: '价格跌破布林带下轨，超卖机会' });
      }
    }

    // KDJ 金叉/死叉
    if (last.k !== null && prev.k !== null && last.d !== null && prev.d !== null) {
      if (prev.k <= prev.d && last.k > last.d && last.k < 30) {
        signals.push({ type: 'BUY', source: '技术面', confidence: 'MEDIUM', reason: 'KDJ低位金叉，反弹信号' });
      }
      if (prev.k >= prev.d && last.k < last.d && last.k > 70) {
        signals.push({ type: 'SELL', source: '技术面', confidence: 'MEDIUM', reason: 'KDJ高位死叉，回调信号' });
      }
    }

    // 量价关系
    if (last.volume !== null && last.volumeMA !== null) {
      if (last.volume > last.volumeMA * 1.5 && last.close > prev.close) {
        signals.push({ type: 'BUY', source: '技术面', confidence: 'MEDIUM', reason: '放量上涨，资金流入' });
      }
      if (last.volume > last.volumeMA * 1.5 && last.close < prev.close) {
        signals.push({ type: 'SELL', source: '技术面', confidence: 'MEDIUM', reason: '放量下跌，资金出逃' });
      }
    }

    // ========== 基本面信号 ==========
    if (fundamental) {
      if (fundamental.totalScore >= 75) {
        signals.push({ type: 'BUY', source: '基本面', confidence: 'MEDIUM', reason: `基本面评分 ${fundamental.totalScore}，质地优秀` });
      }
      if (fundamental.totalScore <= 35) {
        signals.push({ type: 'SELL', source: '基本面', confidence: 'MEDIUM', reason: `基本面评分 ${fundamental.totalScore}，质地较差` });
      }
      const flags = fundamental.flags || [];
      const goodFlags = flags.filter(f => f.includes('优秀') || f.includes('良好') || f.includes('偏低') || f.includes('安全'));
      const badFlags = flags.filter(f => f.includes('过高') || f.includes('弱') || f.includes('压力') || f.includes('风险'));
      goodFlags.slice(0, 2).forEach(f => signals.push({ type: 'BUY', source: '基本面', confidence: 'LOW', reason: f }));
      badFlags.slice(0, 2).forEach(f => signals.push({ type: 'SELL', source: '基本面', confidence: 'LOW', reason: f }));
    }

    // ========== 消息面信号 ==========
    if (sentiment && sentiment.combinedScore !== undefined) {
      if (sentiment.combinedScore >= 2) {
        signals.push({ type: 'BUY', source: '消息面', confidence: 'MEDIUM', reason: `市场情绪积极 (得分 ${sentiment.combinedScore})` });
      }
      if (sentiment.combinedScore <= -2) {
        signals.push({ type: 'SELL', source: '消息面', confidence: 'MEDIUM', reason: `市场情绪悲观 (得分 ${sentiment.combinedScore})` });
      }
      // 个股相关新闻情绪
      if (sentiment.symbolNewsScore !== undefined) {
        if (sentiment.symbolNewsScore >= 3) {
          signals.push({ type: 'BUY', source: '消息面', confidence: 'HIGH', reason: `个股利好新闻集中 (得分 ${sentiment.symbolNewsScore})` });
        }
        if (sentiment.symbolNewsScore <= -3) {
          signals.push({ type: 'SELL', source: '消息面', confidence: 'HIGH', reason: `个股利空新闻集中 (得分 ${sentiment.symbolNewsScore})` });
        }
      }
    }

    // ========== 止损止盈计算 ==========
    const stopLoss = last.atr !== null ? price - this.cfg.stopLossAtrMultiplier * last.atr : null;
    const takeProfit = last.atr !== null ? price + this.cfg.takeProfitAtrMultiplier * last.atr : null;
    const trailingStop = last.ma20 !== null ? last.ma20 : (stopLoss ? stopLoss * 0.98 : null);

    // 信号聚合
    const buySignals = signals.filter(s => s.type === 'BUY');
    const sellSignals = signals.filter(s => s.type === 'SELL');

    let overallSignal = 'HOLD';
    let overallConfidence = 'LOW';
    let overallReason = '暂无明确信号，建议观望';

    const buyHigh = buySignals.filter(s => s.confidence === 'HIGH').length;
    const buyMed = buySignals.filter(s => s.confidence === 'MEDIUM').length;
    const sellHigh = sellSignals.filter(s => s.confidence === 'HIGH').length;
    const sellMed = sellSignals.filter(s => s.confidence === 'MEDIUM').length;

    if (buyHigh >= 2 || (buyHigh >= 1 && buyMed >= 2)) {
      overallSignal = 'STRONG_BUY';
      overallConfidence = 'HIGH';
      overallReason = '多维度共振买入信号';
    } else if (buyHigh >= 1 || buyMed >= 2) {
      overallSignal = 'BUY';
      overallConfidence = 'MEDIUM';
      overallReason = '出现买入信号';
    } else if (sellHigh >= 2 || (sellHigh >= 1 && sellMed >= 2)) {
      overallSignal = 'STRONG_SELL';
      overallConfidence = 'HIGH';
      overallReason = '多维度共振卖出信号';
    } else if (sellHigh >= 1 || sellMed >= 2) {
      overallSignal = 'SELL';
      overallConfidence = 'MEDIUM';
      overallReason = '出现卖出信号';
    }

    return {
      signals,
      buyCount: buySignals.length,
      sellCount: sellSignals.length,
      overallSignal,
      overallConfidence,
      overallReason,
      stopLoss: stopLoss ? +stopLoss.toFixed(2) : null,
      takeProfit: takeProfit ? +takeProfit.toFixed(2) : null,
      trailingStop: trailingStop ? +trailingStop.toFixed(2) : null,
      riskRewardRatio: (stopLoss && takeProfit && price)
        ? +((takeProfit - price) / (price - stopLoss)).toFixed(2)
        : null
    };
  }
}

module.exports = SignalEngine;
