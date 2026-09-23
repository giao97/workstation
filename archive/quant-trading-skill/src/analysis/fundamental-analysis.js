/**
 * 基本面分析引擎
 * 综合估值、质量、成长、风险四个维度
 */
class FundamentalAnalysis {
  analyze(quote, fundamentals) {
    if (!quote && !fundamentals) return null;

    const scores = { valuation: 50, quality: 50, growth: 50, risk: 50 };
    const flags = [];

    // ===== 估值维度 =====
    const pe = quote?.pe || fundamentals?.pe;
    const pb = quote?.pb || fundamentals?.pb;
    const forwardPE = quote?.forwardPE || fundamentals?.forwardPE;

    if (pe !== undefined && pe !== null) {
      if (pe < 15) { scores.valuation += 20; flags.push('PE估值偏低，具备安全边际'); }
      else if (pe < 25) { scores.valuation += 10; flags.push('PE估值合理'); }
      else if (pe > 40) { scores.valuation -= 15; flags.push('PE估值偏高，注意风险'); }
      else if (pe > 60) { scores.valuation -= 25; flags.push('PE估值过高，泡沫风险'); }
    }

    if (pb !== undefined && pb !== null) {
      if (pb < 1.5) { scores.valuation += 10; flags.push('PB低于1.5，资产端安全'); }
      else if (pb > 5) { scores.valuation -= 10; flags.push('PB过高，资产溢价明显'); }
    }

    if (forwardPE && pe && forwardPE < pe * 0.85) {
      scores.growth += 10;
      flags.push('远期PE低于当前PE，盈利预期改善');
    }

    // ===== 质量维度 =====
    const roe = fundamentals?.roe;
    const roa = fundamentals?.roa;
    const profitMargins = fundamentals?.profitMargins;

    if (roe !== undefined && roe !== null) {
      if (roe > 0.15) { scores.quality += 20; flags.push(`ROE ${(roe*100).toFixed(1)}%，股东回报优秀`); }
      else if (roe > 0.10) { scores.quality += 10; flags.push(`ROE ${(roe*100).toFixed(1)}%，股东回报良好`); }
      else if (roe < 0.05) { scores.quality -= 15; flags.push(`ROE ${(roe*100).toFixed(1)}%，盈利能力弱`); }
    }

    if (roa !== undefined && roa !== null) {
      if (roa > 0.08) scores.quality += 10;
      else if (roa < 0.03) scores.quality -= 10;
    }

    if (profitMargins !== undefined && profitMargins !== null) {
      if (profitMargins > 0.20) { scores.quality += 10; flags.push('净利润率超20%，商业模式优秀'); }
      else if (profitMargins < 0.05) { scores.quality -= 10; flags.push('净利润率偏低，成本控制压力大'); }
    }

    // ===== 成长维度 =====
    const revenueGrowth = fundamentals?.revenueGrowth;
    const earningsGrowth = fundamentals?.earningsGrowth;

    if (revenueGrowth !== undefined && revenueGrowth !== null) {
      if (revenueGrowth > 0.30) { scores.growth += 20; flags.push(`营收增速 ${(revenueGrowth*100).toFixed(1)}%，高速增长`); }
      else if (revenueGrowth > 0.15) { scores.growth += 10; flags.push(`营收增速 ${(revenueGrowth*100).toFixed(1)}%，稳健增长`); }
      else if (revenueGrowth < 0) { scores.growth -= 15; flags.push(`营收负增长 ${(revenueGrowth*100).toFixed(1)}%，成长承压`); }
    }

    if (earningsGrowth !== undefined && earningsGrowth !== null) {
      if (earningsGrowth > 0.25) scores.growth += 10;
      else if (earningsGrowth < -0.10) scores.growth -= 10;
    }

    // ===== 风险维度 =====
    const debtToEquity = fundamentals?.debtToEquity;
    const currentRatio = fundamentals?.currentRatio;

    if (debtToEquity !== undefined && debtToEquity !== null) {
      if (debtToEquity > 1.0) { scores.risk -= 15; flags.push(`负债率 ${(debtToEquity*100).toFixed(1)}%，杠杆偏高`); }
      else if (debtToEquity < 0.5) { scores.risk += 10; flags.push('负债率低，财务稳健'); }
    }

    if (currentRatio !== undefined && currentRatio !== null) {
      if (currentRatio < 1.0) { scores.risk -= 10; flags.push('流动比率低于1，短期偿债压力大'); }
      else if (currentRatio > 2.0) scores.risk += 5;
    }

    // ===== 分析师共识 =====
    const recommendation = fundamentals?.recommendationKey;
    const targetMean = fundamentals?.targetMeanPrice;
    const currentPrice = quote?.price;

    if (recommendation) {
      const recMap = { strong_buy: 15, buy: 10, hold: 0, sell: -10, strong_sell: -15 };
      const recScore = recMap[recommendation] || 0;
      scores.valuation += recScore;
      flags.push(`分析师共识: ${recommendation.replace('_', ' ')}`);
    }

    if (targetMean && currentPrice && targetMean > currentPrice * 1.15) {
      scores.valuation += 10;
      flags.push(`目标价 ${targetMean.toFixed(2)}，上涨空间 ${((targetMean/currentPrice-1)*100).toFixed(1)}%`);
    }

    // 总分
    const totalScore = Math.round((scores.valuation + scores.quality + scores.growth + scores.risk) / 4);
    let rating = '中性';
    if (totalScore >= 75) rating = '优秀';
    else if (totalScore >= 60) rating = '良好';
    else if (totalScore <= 40) rating = '较差';
    else if (totalScore <= 30) rating = '危险';

    return {
      scores,
      totalScore,
      rating,
      flags,
      raw: { pe, pb, forwardPE, roe, roa, revenueGrowth, earningsGrowth, debtToEquity, currentRatio, recommendation, targetMean }
    };
  }
}

module.exports = FundamentalAnalysis;
