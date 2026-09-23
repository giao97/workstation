const nodemailer = require('nodemailer');

/**
 * 提醒通知器
 * 支持邮件提醒，可扩展为钉钉/企业微信/飞书
 */
class Notifier {
  constructor(emailConfig) {
    this.emailConfig = emailConfig;
    this.transporter = null;
    if (emailConfig && emailConfig.host && emailConfig.user) {
      this.transporter = nodemailer.createTransport({
        host: emailConfig.host,
        port: emailConfig.port || 465,
        secure: (emailConfig.port || 465) === 465,
        auth: {
          user: emailConfig.user,
          pass: emailConfig.pass
        }
      });
    }
  }

  async sendEmail(subject, html, to) {
    if (!this.transporter) {
      console.log('[Notifier] Email not configured, skipping email notification');
      return false;
    }
    try {
      await this.transporter.sendMail({
        from: `"量化交易助手" <${this.emailConfig.user}>`,
        to: to || this.emailConfig.to,
        subject,
        html
      });
      console.log('[Notifier] Email sent successfully');
      return true;
    } catch (err) {
      console.error('[Notifier] Email failed:', err.message);
      return false;
    }
  }

  async alertTradeSignal(symbol, signal, quote) {
    const subject = `[交易信号] ${symbol} - ${signal.overallSignal}`;
    const html = `
      <h2>${symbol} 交易信号提醒</h2>
      <p><strong>信号:</strong> ${signal.overallSignal} (${signal.overallConfidence})</p>
      <p><strong>理由:</strong> ${signal.overallReason}</p>
      <p><strong>当前价格:</strong> ${quote?.price || '-'}</p>
      <p><strong>止损位:</strong> ${signal.stopLoss || '-'} | <strong>止盈位:</strong> ${signal.takeProfit || '-'}</p>
      <hr>
      <p>详细报告请查看本地生成的日报文件。</p>
    `;
    return this.sendEmail(subject, html);
  }

  async alertDailyReport(reportPath) {
    const dateStr = new Date().toISOString().split('T')[0];
    const subject = `[日报] 量化交易日报 - ${dateStr}`;
    const html = `<h2>今日量化交易日报已生成</h2><p>报告路径: ${reportPath}</p><p>请打开 HTML 文件查看完整分析。</p>`;
    return this.sendEmail(subject, html);
  }

  async alertNewsFlash(newsItem) {
    const subject = `[快讯] ${newsItem.source} - ${newsItem.title.slice(0, 40)}`;
    const html = `<h3>${newsItem.title}</h3><p>${newsItem.summary || ''}</p><p>来源: ${newsItem.source}</p>`;
    return this.sendEmail(subject, html);
  }

  // 控制台提醒 (不依赖邮件)
  consoleAlert(symbol, signal) {
    const icon = signal.overallSignal.includes('BUY') ? '\u{1F7E2}' : signal.overallSignal.includes('SELL') ? '\u{1F534}' : '\u{1F7E1}';
    console.log(`${icon} [${symbol}] ${signal.overallSignal} | 止损: ${signal.stopLoss} | 止盈: ${signal.takeProfit} | ${signal.overallReason}`);
  }
}

module.exports = Notifier;
