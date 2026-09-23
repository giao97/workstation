const fs = require('fs-extra');
const path = require('path');

class ReportGenerator {
  constructor(reportDir) {
    this.reportDir = reportDir;
    fs.ensureDirSync(reportDir);
  }

  getDateStr() {
    return new Date().toISOString().split('T')[0];
  }

  async generateHTML(results, newsAnalysis, policyAnalysis, marketSentiment) {
    const dateStr = this.getDateStr();
    const filePath = path.join(this.reportDir, `report_${dateStr}.html`);

    const stockCards = results.map(r => this.buildStockCard(r)).join('\n');
    const newsSection = this.buildNewsSection(newsAnalysis);
    const policySection = this.buildPolicySection(policyAnalysis);
    const sentimentSection = this.buildSentimentSection(marketSentiment);
    const chartScripts = results.map((r, i) => this.buildChartScript(r, i)).join('\n');
    const chartDivs = results.map((r, i) => `<div id="chart-${i}" style="height:400px;margin-bottom:20px;border:1px solid #334155;border-radius:8px;overflow:hidden;"></div>`).join('\n');

    const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>量化交易日报 - ${dateStr}</title>
  <script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #e2e8f0; line-height: 1.6; padding: 20px; }
    .container { max-width: 1400px; margin: 0 auto; }
    h1 { font-size: 28px; color: #38bdf8; margin-bottom: 8px; }
    .subtitle { color: #94a3b8; font-size: 14px; margin-bottom: 24px; }
    .section { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid #334155; }
    .section h2 { font-size: 18px; color: #7dd3fc; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 16px; }
    .card { background: #0f172a; border-radius: 10px; padding: 16px; border: 1px solid #334155; transition: border-color 0.2s; }
    .card:hover { border-color: #38bdf8; }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .symbol { font-size: 20px; font-weight: 700; color: #f8fafc; }
    .badge { padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; }
    .badge-buy { background: #065f46; color: #34d399; }
    .badge-sell { background: #7f1d1d; color: #f87171; }
    .badge-hold { background: #713f12; color: #fbbf24; }
    .badge-strong-buy { background: #047857; color: #6ee7b7; }
    .badge-strong-sell { background: #991b1b; color: #fca5a5; }
    .price-row { display: flex; gap: 16px; margin-bottom: 12px; flex-wrap: wrap; }
    .price-item { display: flex; flex-direction: column; }
    .price-label { font-size: 11px; color: #94a3b8; text-transform: uppercase; }
    .price-value { font-size: 16px; font-weight: 600; }
    .price-up { color: #34d399; }
    .price-down { color: #f87171; }
    .signals { display: flex; flex-direction: column; gap: 6px; }
    .signal { font-size: 13px; padding: 6px 10px; border-radius: 6px; background: #1e293b; display: flex; gap: 8px; align-items: center; }
    .signal-type { font-weight: 700; min-width: 36px; }
    .signal-buy { color: #34d399; }
    .signal-sell { color: #f87171; }
    .signal-source { color: #94a3b8; font-size: 11px; }
    .levels { display: flex; gap: 12px; margin-top: 12px; padding-top: 12px; border-top: 1px solid #334155; }
    .level { text-align: center; }
    .level-label { font-size: 11px; color: #94a3b8; }
    .level-value { font-size: 14px; font-weight: 600; }
    .level-stop { color: #f87171; }
    .level-profit { color: #34d399; }
    .score-bar { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
    .score-track { flex: 1; height: 6px; background: #334155; border-radius: 3px; overflow: hidden; }
    .score-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
    .score-fill-good { background: #34d399; }
    .score-fill-mid { background: #fbbf24; }
    .score-fill-bad { background: #f87171; }
    .news-list, .policy-list { display: flex; flex-direction: column; gap: 10px; }
    .news-item { padding: 12px; background: #0f172a; border-radius: 8px; border-left: 3px solid #334155; }
    .news-item.positive { border-left-color: #34d399; }
    .news-item.negative { border-left-color: #f87171; }
    .news-title { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
    .news-meta { font-size: 12px; color: #94a3b8; display: flex; gap: 12px; }
    .sentiment-score { font-size: 24px; font-weight: 700; }
    .sentiment-positive { color: #34d399; }
    .sentiment-negative { color: #f87171; }
    .sentiment-neutral { color: #fbbf24; }
    .summary-box { background: #0f172a; padding: 16px; border-radius: 8px; margin-top: 12px; white-space: pre-wrap; font-size: 14px; line-height: 1.8; }
    .tech-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 8px; }
    .tech-item { text-align: center; padding: 8px; background: #1e293b; border-radius: 6px; }
    .tech-label { font-size: 11px; color: #94a3b8; }
    .tech-value { font-size: 14px; font-weight: 600; }
    .chart-section { margin-top: 16px; }
    .chart-tabs { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
    .chart-tab { padding: 6px 14px; background: #1e293b; border: 1px solid #334155; border-radius: 6px; cursor: pointer; font-size: 13px; }
    .chart-tab.active { background: #38bdf8; color: #0f172a; border-color: #38bdf8; }
  </style>
</head>
<body>
  <div class="container">
    <h1>\u{1F4C8} 量化交易日报</h1>
    <p class="subtitle">生成时间: ${new Date().toLocaleString('zh-CN')} | 数据覆盖: A股 + 美股 | 图表引擎: TradingView (Lightweight Charts)</p>

    <div class="section">
      <h2>\u{1F4CA} 市场情绪概览</h2>
      ${sentimentSection}
    </div>

    <div class="section">
      <h2>\u{1F4B9} 个股分析与交易信号</h2>
      <div class="grid">${stockCards}</div>
    </div>

    <div class="section">
      <h2>\u{1F4C9} K线图表 (TradingView 风格)</h2>
      <div class="chart-tabs">
        ${results.map((r, i) => `<button class="chart-tab ${i===0?'active':''}" onclick="showChart(${i})">${r.symbol}</button>`).join('')}
      </div>
      <div id="chart-container">${chartDivs}</div>
    </div>

    <div class="section">
      <h2>\u{1F4DD} 重点政策解读</h2>
      ${policySection}
    </div>

    <div class="section">
      <h2>\u{1F4F0} 重要财经新闻</h2>
      ${newsSection}
    </div>
  </div>

  <script>
    function showChart(idx) {
      document.querySelectorAll('[id^="chart-"]').forEach((el, i) => {
        el.style.display = i === idx ? 'block' : 'none';
      });
      document.querySelectorAll('.chart-tab').forEach((el, i) => {
        el.classList.toggle('active', i === idx);
      });
    }
    ${chartScripts}
    showChart(0);
  </script>
</body>
</html>`;

    await fs.writeFile(filePath, html, 'utf8');
    return filePath;
  }

  buildChartScript(result, index) {
    const data = result.historical || [];
    const tech = result.technical?.trend || {};
    const candleData = JSON.stringify(data.map((d, i) => ({
      time: d.date.replace(/-/g, ''),
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close
    })));

    const ma20Data = JSON.stringify((tech.ma20 || []).map((v, i) => v !== null ? { time: data[i]?.date?.replace(/-/g, ''), value: v } : null).filter(Boolean));
    const bbUpperData = JSON.stringify((tech.bollinger?.upper || []).map((v, i) => v !== null ? { time: data[i]?.date?.replace(/-/g, ''), value: v } : null).filter(Boolean));
    const bbLowerData = JSON.stringify((tech.bollinger?.lower || []).map((v, i) => v !== null ? { time: data[i]?.date?.replace(/-/g, ''), value: v } : null).filter(Boolean));
    const volumeData = JSON.stringify(data.map((d, i) => ({ time: d.date.replace(/-/g, ''), value: d.volume })));

    return `
    (function(){
      const chart = LightweightCharts.createChart(document.getElementById('chart-${index}'), {
        layout: { background: { color: '#0f172a' }, textColor: '#e2e8f0' },
        grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#334155' },
        timeScale: { borderColor: '#334155' }
      });
      const candleSeries = chart.addCandlestickSeries({
        upColor: '#ef4444', downColor: '#22c55e', borderUpColor: '#ef4444', borderDownColor: '#22c55e',
        wickUpColor: '#ef4444', wickDownColor: '#22c55e'
      });
      candleSeries.setData(${candleData});

      const maSeries = chart.addLineSeries({ color: '#38bdf8', lineWidth: 2, title: 'MA20' });
      maSeries.setData(${ma20Data});

      const bbUpper = chart.addLineSeries({ color: '#f97316', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, title: 'BB Upper' });
      bbUpper.setData(${bbUpperData});
      const bbLower = chart.addLineSeries({ color: '#f97316', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, title: 'BB Lower' });
      bbLower.setData(${bbLowerData});

      const volumeSeries = chart.addHistogramSeries({
        color: '#64748b', priceFormat: { type: 'volume' }, priceScaleId: ''
      });
      volumeSeries.setData(${volumeData});
      chart.priceScale('').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

      chart.timeScale().fitContent();
    })();`;
  }

  buildStockCard(r) {
    const sig = r.signals;
    const tech = r.technical?.latest || {};
    const fund = r.fundamental;
    const quote = r.quote || {};

    const badgeClass = {
      'STRONG_BUY': 'badge-strong-buy', 'BUY': 'badge-buy',
      'SELL': 'badge-sell', 'STRONG_SELL': 'badge-strong-sell', 'HOLD': 'badge-hold'
    }[sig.overallSignal] || 'badge-hold';
    const badgeText = { 'STRONG_BUY': '强烈买入', 'BUY': '买入', 'SELL': '卖出', 'STRONG_SELL': '强烈卖出', 'HOLD': '观望' }[sig.overallSignal] || '观望';

    const signalHtml = sig.signals.slice(0, 6).map(s => {
      const cls = s.type === 'BUY' ? 'signal-buy' : 'signal-sell';
      return `<div class="signal"><span class="signal-type ${cls}">${s.type}</span><span>${s.reason}</span><span class="signal-source">${s.source}\u00B7${s.confidence}</span></div>`;
    }).join('');

    const fundScore = fund ? fund.totalScore : 50;
    const scoreFillClass = fundScore >= 70 ? 'score-fill-good' : fundScore >= 45 ? 'score-fill-mid' : 'score-fill-bad';

    return `
    <div class="card">
      <div class="card-header">
        <span class="symbol">${r.symbol}${quote.name ? ` <span style="font-size:14px;color:#94a3b8">${quote.name}</span>` : ''}</span>
        <span class="badge ${badgeClass}">${badgeText}</span>
      </div>
      <div class="price-row">
        <div class="price-item"><span class="price-label">当前价</span><span class="price-value">${quote.price?.toFixed(2) || tech.close?.toFixed(2) || '-'}</span></div>
        <div class="price-item"><span class="price-label">涨跌幅</span><span class="price-value ${quote.changePercent >= 0 ? 'price-up' : 'price-down'}">${quote.changePercent ? (quote.changePercent > 0 ? '+' : '') + quote.changePercent.toFixed(2) + '%' : '-'}</span></div>
        <div class="price-item"><span class="price-label">基本面评分</span><span class="price-value">${fundScore}/100</span></div>
      </div>
      <div class="score-bar"><div class="score-track"><div class="score-fill ${scoreFillClass}" style="width:${fundScore}%"></div></div></div>
      <div class="tech-grid" style="margin-top:12px">
        <div class="tech-item"><div class="tech-label">RSI(14)</div><div class="tech-value">${tech.rsi?.toFixed(1) || '-'}</div></div>
        <div class="tech-item"><div class="tech-label">MA20</div><div class="tech-value">${tech.ma20?.toFixed(2) || '-'}</div></div>
        <div class="tech-item"><div class="tech-label">MACD</div><div class="tech-value">${tech.macd?.toFixed(3) || '-'}</div></div>
        <div class="tech-item"><div class="tech-label">布林带</div><div class="tech-value">${tech.bbUpper?.toFixed(2) || '-'}</div></div>
        <div class="tech-item"><div class="tech-label">KDJ-K</div><div class="tech-value">${tech.k?.toFixed(1) || '-'}</div></div>
        <div class="tech-item"><div class="tech-label">ATR(14)</div><div class="tech-value">${tech.atr?.toFixed(3) || '-'}</div></div>
      </div>
      <div class="signals" style="margin-top:12px">${signalHtml}</div>
      <div class="levels">
        <div class="level"><div class="level-label">止损位</div><div class="level-value level-stop">${sig.stopLoss || '-'}</div></div>
        <div class="level"><div class="level-label">止盈位</div><div class="level-value level-profit">${sig.takeProfit || '-'}</div></div>
        <div class="level"><div class="level-label">移动止损</div><div class="level-value level-stop">${sig.trailingStop || '-'}</div></div>
        <div class="level"><div class="level-label">盈亏比</div><div class="level-value">${sig.riskRewardRatio || '-'}</div></div>
      </div>
    </div>`;
  }

  buildNewsSection(newsAnalysis) {
    if (!newsAnalysis || newsAnalysis.length === 0) return '<p style="color:#94a3b8">暂无新闻数据</p>';
    const items = newsAnalysis.slice(0, 10).map(n => {
      const cls = n.sentimentScore > 0 ? 'positive' : n.sentimentScore < 0 ? 'negative' : '';
      return `<div class="news-item ${cls}"><div class="news-title">${n.title}</div><div class="news-meta"><span>${n.source}</span><span>${n.sentiment || '中性'} (${n.sentimentScore > 0 ? '+' : ''}${n.sentimentScore})</span><span>${n.publishTime ? new Date(n.publishTime).toLocaleString('zh-CN') : ''}</span></div></div>`;
    }).join('');
    return `<div class="news-list">${items}</div>`;
  }

  buildPolicySection(policyAnalysis) {
    if (!policyAnalysis || !policyAnalysis.policies || policyAnalysis.policies.length === 0) {
      return '<p style="color:#94a3b8">暂无政策数据</p>';
    }
    const items = policyAnalysis.policies.slice(0, 8).map(p => {
      const cls = p.sentimentScore > 0 ? 'positive' : p.sentimentScore < 0 ? 'negative' : '';
      return `<div class="news-item ${cls}"><div class="news-title">[${p.source}] ${p.title}</div><div class="news-meta"><span>${p.category}</span><span>${p.sentiment || '中性'}</span><span>${p.publishTime || ''}</span></div></div>`;
    }).join('');
    return `<div class="policy-list">${items}</div><div style="margin-top:12px;padding:12px;background:#0f172a;border-radius:8px"><strong>政策影响评估:</strong> ${policyAnalysis.impact} (\u5E73\u5747\u5F97\u5206: ${policyAnalysis.avgScore})</div>`;
  }

  buildSentimentSection(sentiment) {
    if (!sentiment) return '<p style="color:#94a3b8">暂无情绪数据</p>';
    const scoreClass = sentiment.combinedScore > 1 ? 'sentiment-positive' : sentiment.combinedScore < -1 ? 'sentiment-negative' : 'sentiment-neutral';
    return `<div style="display:flex;gap:24px;align-items:center;flex-wrap:wrap"><div><div class="sentiment-score ${scoreClass}">${sentiment.combinedScore > 0 ? '+' : ''}${sentiment.combinedScore}</div><div style="font-size:12px;color:#94a3b8">综合情绪得分</div></div><div style="flex:1;min-width:300px"><div style="display:flex;gap:16px;margin-bottom:8px"><div><span style="color:#94a3b8">整体判断:</span> <strong>${sentiment.overall}</strong></div><div><span style="color:#94a3b8">新闻情绪:</span> ${sentiment.newsScore > 0 ? '+' : ''}${sentiment.newsScore}</div><div><span style="color:#94a3b8">政策情绪:</span> ${sentiment.policyScore > 0 ? '+' : ''}${sentiment.policyScore}</div></div><div class="summary-box">${sentiment.summary}</div></div></div>`;
  }

  async generateJSON(results, newsAnalysis, policyAnalysis, marketSentiment) {
    const dateStr = this.getDateStr();
    const filePath = path.join(this.reportDir, `report_${dateStr}.json`);
    const report = { date: dateStr, generatedAt: new Date().toISOString(), marketSentiment, policyAnalysis, newsAnalysis: newsAnalysis?.slice(0, 20), stocks: results.map(r => ({ symbol: r.symbol, quote: r.quote, technical: r.technical?.latest, fundamental: r.fundamental, signals: r.signals })) };
    await fs.writeJson(filePath, report, { spaces: 2 });
    return filePath;
  }

  async generateMarkdown(results, newsAnalysis, policyAnalysis, marketSentiment) {
    const dateStr = this.getDateStr();
    const filePath = path.join(this.reportDir, `report_${dateStr}.md`);
    const lines = [`# 量化交易日报 - ${dateStr}`, `> \u751F\u6210\u65F6\u95F4: ${new Date().toLocaleString('zh-CN')}`, '', '## \u5E02\u573A\u60C5\u7EEA\u6982\u89C8', `- **整体判断**: ${marketSentiment?.overall || '暂无数据'}`, `- **\u7EFC\u5408\u5F97\u5206**: ${marketSentiment?.combinedScore || 0}`, `- **新闻情绪**: ${marketSentiment?.newsScore || 0}`, `- **政策情绪**: ${marketSentiment?.policyScore || 0}`, '', '## \u4E2A\u80A1\u5206\u6790\u4E0E\u4EA4\u6613\u4FE1\u53F7', ''];
    for (const r of results) {
      const sig = r.signals, q = r.quote || {};
      lines.push(`### ${r.symbol}${q.name ? ` (${q.name})` : ''}`);
      lines.push(`- **\u5F53\u524D\u4EF7\u683C**: ${q.price?.toFixed(2) || '-'} | **\u6DA8\u8DCC\u5E45**: ${q.changePercent?.toFixed(2) || '-'}%`);
      lines.push(`- **\u7EFC\u5408\u4FE1\u53F7**: ${sig.overallSignal} (${sig.overallConfidence}) - ${sig.overallReason}`);
      lines.push(`- **\u6B62\u635F\u4F4D**: ${sig.stopLoss || '-'} | **\u6B62\u76C8\u4F4D**: ${sig.takeProfit || '-'} | **\u79FB\u52A8\u6B62\u635F**: ${sig.trailingStop || '-'}`);
      lines.push(`- **\u57FA\u672C\u9762\u8BC4\u5206**: ${r.fundamental?.totalScore || '-'}/100`);
      if (sig.signals.length > 0) { lines.push('- **\u8BE6\u7EC6\u4FE1\u53F7**:'); for (const s of sig.signals.slice(0, 6)) lines.push(`  - [${s.type}] ${s.source}\u00B7${s.confidence}: ${s.reason}`); }
      lines.push('');
    }
    lines.push('## \u91CD\u70B9\u653F\u7B56\u89E3\u8BFB', '');
    if (policyAnalysis?.policies?.length > 0) { for (const p of policyAnalysis.policies.slice(0, 8)) lines.push(`- **[${p.source}]** ${p.title} - ${p.sentiment || '中性'}`); }
    else lines.push('暂无政策数据');
    lines.push('', '## \u91CD\u8981\u8D22\u7ECF\u65B0\u95FB', '');
    if (newsAnalysis?.length > 0) { for (const n of newsAnalysis.slice(0, 10)) lines.push(`- **[${n.source}]** ${n.title} - ${n.sentiment || '中性'} (${n.sentimentScore > 0 ? '+' : ''}${n.sentimentScore})`); }
    else lines.push('暂无新闻数据');
    await fs.writeFile(filePath, lines.join('\n'), 'utf8');
    return filePath;
  }
}

module.exports = ReportGenerator;

