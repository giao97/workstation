/**
 * 新闻政策情绪分析引擎
 * 通过关键词匹配和情绪词典对新闻政策进行打分
 * 支持A股和美股相关政策/新闻的情绪判断
 */
class SentimentAnalysis {
  constructor() {
    // 正面情绪词库
    this.positiveWords = [
      '利好','利好政策','支持','扶持','鼓励','减税','降准','降息','宽松','刺激',
      '增长','上涨','反弹','突破','创新高','强劲','复苏','景气','繁荣','超预期',
      '分红','增持','回购','并购','扩张','盈利','利润增长','营收增长',
      'positive','bullish','rally','surge','growth','strong','beat','outperform',
      'upgrade','buyback','dividend','expansion','recovery','boom','optimistic'
    ];

    // 负面情绪词库
    this.negativeWords = [
      '利空','利空政策','收紧','调控','监管','处罚','罚款','立案调查','退市',
      '风险','暴跌','下跌','崩盘','跌停','破发','亏损','业绩下滑','裁员','债务违约',
      '通胀','加息','缩表','紧缩','制裁','贸易摩擦','地缘政治','黑天鹅',
      'negative','bearish','crash','plunge','recession','decline','miss','underperform',
      'downgrade','bankruptcy','layoff','default','inflation','tightening','sanction'
    ];

    // 行业/板块映射
    this.sectorMap = {
      '新能源': ['新能源','光伏','风电','储能','锂电池','电动车','特斯拉','BYD'],
      '半导体': ['半导体','芯片','集成电路','光刻机','中芯','NVIDIA','TSM'],
      '医药': ['医药','医疗','生物','疫苗','CXO','创新药'],
      '金融': ['银行','保险','证券','券商','金融科技','fintech'],
      '消费': ['消费','白酒','食品饮料','零售','电商','Apple','Tesla'],
      '地产': ['房地产','地产','恒大','万科','保利','住建部'],
      '科技': ['人工智能','AI','云计算','大数据','软件','SaaS','微软','谷歌']
    };
  }

  /**
   * 对单条新闻进行情绪分析
   */
  analyzeItem(item, symbol = null, sector = null) {
    const text = `${item.title} ${item.summary || ''}`.toLowerCase();
    let score = 0;
    const matchedPos = [];
    const matchedNeg = [];

    for (const word of this.positiveWords) {
      if (text.includes(word.toLowerCase())) {
        score += 1;
        matchedPos.push(word);
      }
    }
    for (const word of this.negativeWords) {
      if (text.includes(word.toLowerCase())) {
        score -= 1;
        matchedNeg.push(word);
      }
    }

    // 符号相关性加权
    let relevance = 1;
    if (symbol && text.includes(symbol.toLowerCase())) relevance = 3;
    if (sector) {
      const keywords = this.sectorMap[sector] || [];
      if (keywords.some(k => text.includes(k.toLowerCase()))) relevance = 2;
    }

    const finalScore = score * relevance;
    let sentiment = '中性';
    if (finalScore >= 3) sentiment = '强烈利好';
    else if (finalScore >= 1) sentiment = '利好';
    else if (finalScore <= -3) sentiment = '强烈利空';
    else if (finalScore <= -1) sentiment = '利空';

    return {
      ...item,
      sentimentScore: finalScore,
      sentiment,
      matchedPositive: matchedPos,
      matchedNegative: matchedNeg,
      relevance
    };
  }

  /**
   * 批量分析新闻列表
   */
  analyzeNews(newsList, symbol = null, sector = null) {
    return newsList.map(item => this.analyzeItem(item, symbol, sector));
  }

  /**
   * 分析政策对特定市场/板块的影响
   */
  analyzePolicyImpact(policyList, market = 'a-share') {
    const marketKeywords = {
      'a-share': ['a股','股市','证券','证监会','沪深','上证','深证','创业板','科创板'],
      'us-stock': ['美股','纳斯达克','纽交所','SEC','美联储','Treasury','Wall Street']
    };
    const keywords = marketKeywords[market] || [];

    const relevantPolicies = policyList.filter(p => {
      const text = `${p.title} ${p.summary || ''}`.toLowerCase();
      return keywords.some(k => text.includes(k.toLowerCase()));
    });

    const analyzed = relevantPolicies.map(p => this.analyzeItem(p));
    const avgScore = analyzed.length > 0
      ? analyzed.reduce((sum, a) => sum + a.sentimentScore, 0) / analyzed.length
      : 0;

    let impact = '中性';
    if (avgScore >= 2) impact = '利好';
    else if (avgScore >= 4) impact = '强烈利好';
    else if (avgScore <= -2) impact = '利空';
    else if (avgScore <= -4) impact = '强烈利空';

    return {
      market,
      relevantCount: analyzed.length,
      avgScore: +avgScore.toFixed(2),
      impact,
      policies: analyzed.slice(0, 10)
    };
  }

  /**
   * 生成综合市场情绪摘要
   */
  generateMarketSentiment(newsAnalysis, policyAnalysis) {
    const newsAvg = newsAnalysis.length > 0
      ? newsAnalysis.reduce((s, n) => s + n.sentimentScore, 0) / newsAnalysis.length
      : 0;
    const policyScore = policyAnalysis?.avgScore || 0;
    const combined = newsAvg * 0.4 + policyScore * 0.6;

    let overall = '中性观望';
    if (combined >= 2.5) overall = '积极乐观';
    else if (combined >= 1) overall = '偏乐观';
    else if (combined <= -2.5) overall = '谨慎悲观';
    else if (combined <= -1) overall = '偏悲观';

    const topPositive = newsAnalysis
      .filter(n => n.sentimentScore > 0)
      .sort((a, b) => b.sentimentScore - a.sentimentScore)
      .slice(0, 5);
    const topNegative = newsAnalysis
      .filter(n => n.sentimentScore < 0)
      .sort((a, b) => a.sentimentScore - b.sentimentScore)
      .slice(0, 5);

    return {
      overall,
      combinedScore: +combined.toFixed(2),
      newsScore: +newsAvg.toFixed(2),
      policyScore: +policyScore.toFixed(2),
      topPositive,
      topNegative,
      summary: this.generateSentimentSummary(overall, topPositive, topNegative)
    };
  }

  generateSentimentSummary(overall, pos, neg) {
    const parts = [`当前市场情绪总体判断: ${overall}`];
    if (pos.length > 0) {
      parts.push(`主要利好因素: ${pos.slice(0, 3).map(p => p.title).join('；')}`);
    }
    if (neg.length > 0) {
      parts.push(`主要利空因素: ${neg.slice(0, 3).map(n => n.title).join('；')}`);
    }
    return parts.join('\n');
  }
}

module.exports = SentimentAnalysis;
