"""
提醒通知模块 - 邮件提醒
"""
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from html import escape
from pathlib import Path
from typing import List, Dict, Any

from config import EMAIL_CONFIG

logger = logging.getLogger("quant_trading")


class EmailNotifier:
    """邮件提醒器"""

    def __init__(self):
        self.cfg = EMAIL_CONFIG

    def is_configured(self) -> bool:
        return bool(self.cfg.get("smtp_user") and self.cfg.get("smtp_pass"))

    def _send(
        self,
        subject: str,
        html: str,
        recipients: List[str] = None,
        attachments: List[str] = None,
    ) -> bool:
        if not self.is_configured():
            logger.info("邮件未配置，跳过发送")
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.cfg["smtp_user"]
            to = recipients or self.cfg.get("recipients", [])
            if not to:
                to = [self.cfg["smtp_user"]]
            msg["To"] = ", ".join(to)
            msg.attach(MIMEText(html, "html", "utf-8"))
            for attachment_path in attachments or []:
                path = Path(attachment_path)
                if not path.exists():
                    logger.warning(f"邮件附件不存在: {path}")
                    continue
                with path.open("rb") as handle:
                    attachment = MIMEApplication(handle.read(), _subtype="html")
                attachment.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=path.name,
                )
                msg.attach(attachment)

            with smtplib.SMTP_SSL(self.cfg["smtp_host"], self.cfg["smtp_port"]) as server:
                server.login(self.cfg["smtp_user"], self.cfg["smtp_pass"])
                server.sendmail(self.cfg["smtp_user"], to, msg.as_string())
            logger.info(f"邮件发送成功: {subject}")
            return True
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            return False

    def send_report_alert(self, report_path: str, results: List[Dict]):
        """发送日报提醒"""
        stem = Path(report_path).stem
        date = stem.removeprefix("daily_summary_").removeprefix("report_").replace("_", "-")
        actionable = [
            result
            for result in results
            if result.get("signal", {}).get("overall_signal", "HOLD") != "HOLD"
        ]
        strong_signals = [result for result in actionable if result.get("signal", {}).get("overall_signal", "").startswith("STRONG")]
        subject = f"[量化日报] {date} - {len(actionable)} 个非观望信号"

        rows = []
        for result in actionable[:15]:
            signal = result.get("signal") or {}
            technical = result.get("technical") or {}
            rows.append(
                "<tr>"
                f"<td>{escape(str(result.get('code', '')))} {escape(str(result.get('name', '')))}</td>"
                f"<td>{escape(str(signal.get('overall_signal', 'HOLD')))}</td>"
                f"<td>{escape(str(technical.get('close', '-')))}</td>"
                f"<td>{escape(str(signal.get('stop_loss', '-')))}</td>"
                f"<td>{escape(str(signal.get('take_profit', '-')))}</td>"
                f"<td>{escape(str(signal.get('overall_reason', '')))}</td>"
                "</tr>"
            )
        html = f"""<h2>量化交易日报已生成</h2>
        <p>日期: {date}</p>
        <p>非观望信号: {len(actionable)} 个，其中强烈信号: {len(strong_signals)} 个。</p>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
        <tr><th>标的</th><th>信号</th><th>现价</th><th>止损</th><th>止盈</th><th>理由</th></tr>
        {''.join(rows)}
        </table>
        <p>完整 HTML 报告已作为附件发送。</p>"""
        return self._send(subject, html, attachments=[report_path])

    def send_trade_alert(self, symbol: str, signal: Dict, quote: Dict):
        """发送交易信号提醒"""
        subject = f"[交易信号] {symbol} - {signal.get('overall_signal', 'HOLD')}"
        html = f"""<h2>{symbol} 交易信号</h2>
        <p><b>信号:</b> {signal.get('overall_signal')} ({signal.get('overall_confidence')})</p>
        <p><b>理由:</b> {signal.get('overall_reason')}</p>
        <p><b>止损:</b> {signal.get('stop_loss')} | <b>止盈:</b> {signal.get('take_profit')}</p>"""
        return self._send(subject, html)
