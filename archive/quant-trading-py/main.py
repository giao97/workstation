"""
主入口 - 量化交易模块，支持全流程/单步执行模式
"""
import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import schedule

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LOG_CONFIG, A_STOCK_WATCHLIST, HK_STOCK_WATCHLIST, US_STOCK_WATCHLIST
from src.analysis.data_quality import analyze_data_quality
from src.data.fetch_yahoo import YahooDataFetcher
from src.data.fetch_akshare import AkshareDataFetcher
from src.data.fetch_news import NewsFetcher
from src.data.fetch_policy import PolicyFetcher
from src.data.storage import DataStorage
from src.data.schema import normalize_ohlcv
from src.data.run_store import RunTracker
from src.analysis.technical import TechnicalAnalyzer
from src.analysis.fundamental import FundamentalAnalyzer
from src.analysis.sentiment import SentimentAnalyzer
from src.analysis.translator import NewsTranslator
from src.analysis.signals import SignalEngine
from src.backtest.backtester import DailyBacktester
from src.report.generator import ReportGenerator
from src.report.backtest_report import generate_backtest_report
from src.report.news_report import NewsReportGenerator
from src.alert.notifier import EmailNotifier
from src.alert.push import WeChatPusher
from src.risk.portfolio import PositionSizer


def setup_logging():
    """配置日志"""
    LOG_CONFIG["file"].parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, LOG_CONFIG["level"].upper(), logging.INFO),
        format=LOG_CONFIG["format"],
        datefmt=LOG_CONFIG["datefmt"],
        handlers=[
            logging.FileHandler(LOG_CONFIG["file"], encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("quant_trading")


def _build_chart_data(df: pd.DataFrame, limit: int = 180) -> list:
    """Keep a compact row set for lightweight-charts without embedding all history."""
    if df is None or df.empty:
        return []

    columns = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "ma5",
        "ma20",
        "ma60",
        "bb_upper",
        "bb_middle",
        "bb_lower",
    ]
    rows = df.tail(limit).copy()
    chart_rows = []
    for _, row in rows.iterrows():
        item = {}
        for column in columns:
            if column not in row or pd.isna(row[column]):
                continue
            value = row[column]
            if column == "date":
                item[column] = pd.Timestamp(value).strftime("%Y-%m-%d")
            else:
                item[column] = float(value)
        if item.get("date") and item.get("close") is not None:
            chart_rows.append(item)
    return chart_rows


def run_fetch(logger):
    """数据抓取模式 - 抓取行情+新闻+政策"""
    logger.info("=" * 50)
    logger.info("开始数据抓取")
    storage = DataStorage()
    stats = {
        "a_kline": 0,
        "a_fundamental": 0,
        "hk_kline": 0,
        "us_history": 0,
        "us_info": 0,
        "news": 0,
        "policies": 0,
    }

    # 抓取A股数据 (akshare)
    ak = AkshareDataFetcher()
    try:
        a_quotes = ak.get_a_spot_quotes(list(A_STOCK_WATCHLIST))
    except Exception as e:
        logger.error(f"抓取A股实时行情失败: {e}")
        a_quotes = {}

    for code in A_STOCK_WATCHLIST:
        try:
            logger.info(f"抓取A股 {code} ...")
            kline = ak.get_daily_kline(code)
            if kline is not None:
                storage.save_csv(kline, f"akshare_kline_{code}.csv", subdir="kline")
                stats["a_kline"] += 1
            realtime = a_quotes.get(code)
            if realtime is not None:
                storage.save_json(realtime, f"akshare_realtime_{code}.json", subdir="realtime")
            fundamental = ak.get_fundamental(code)
            if fundamental is not None:
                storage.save_json(fundamental, f"akshare_fundamental_{code}.json", subdir="fundamental")
                stats["a_fundamental"] += 1
        except Exception as e:
            logger.error(f"抓取A股 {code} 失败: {e}")

    # 抓取港股数据 (akshare)
    try:
        hk_quotes = ak.get_hk_spot_quotes(list(HK_STOCK_WATCHLIST))
    except Exception as e:
        logger.error(f"抓取港股实时行情失败: {e}")
        hk_quotes = {}

    for code in HK_STOCK_WATCHLIST:
        try:
            logger.info(f"抓取港股 {code} ...")
            kline = ak.get_hk_daily_kline(code)
            if kline is not None:
                storage.save_csv(kline, f"akshare_hk_kline_{code}.csv", subdir="kline")
                stats["hk_kline"] += 1
            realtime = hk_quotes.get(code)
            if realtime is not None:
                storage.save_json(realtime, f"akshare_hk_realtime_{code}.json", subdir="realtime")
        except Exception as e:
            logger.error(f"抓取港股 {code} 失败: {e}")

    # 抓取美股数据 (yfinance)
    yf = YahooDataFetcher()
    for ticker in US_STOCK_WATCHLIST:
        try:
            logger.info(f"抓取美股 {ticker} ...")
            hist = yf.get_history(ticker, period="6mo")
            if hist is not None:
                storage.save_csv(hist, f"yahoo_history_{ticker}.csv", subdir="history")
                stats["us_history"] += 1
            info = yf.get_info(ticker)
            if info is not None:
                storage.save_json(info, f"yahoo_info_{ticker}.json", subdir="info")
                stats["us_info"] += 1
        except Exception as e:
            logger.error(f"抓取美股 {ticker} 失败: {e}")

    # 抓取新闻
    nf = NewsFetcher()
    try:
        logger.info("抓取新闻 ...")
        news = nf.fetch_all_news(per_source_limit=20)
        stats["news"] = len(news)
        storage.save_snapshot_json(news, "all_news.json", subdir="news")

        # 生成每日新闻总结
        news_summary = nf.generate_daily_summary(news)
        storage.save_snapshot_json(news_summary, "news_summary.json", subdir="news")
        logger.info(f"新闻总结: 共{news_summary['total_news']}条，涉及{len(news_summary['stock_summaries'])}只个股")
    except Exception as e:
        logger.error(f"抓取新闻失败: {e}")

    # 抓取政策
    pf = PolicyFetcher()
    try:
        logger.info("抓取政策 ...")
        policies = pf.fetch_all_policies()
        stats["policies"] = len(policies)
        storage.save_snapshot_json(policies, "all_policies.json", subdir="policy")
    except Exception as e:
        logger.error(f"抓取政策失败: {e}")

    logger.info("数据抓取完成")
    logger.info(
        "抓取统计: A股K线%d/基本面%d | 港股K线%d | 美股历史%d/信息%d | 新闻%d | 政策%d",
        stats["a_kline"],
        stats["a_fundamental"],
        stats["hk_kline"],
        stats["us_history"],
        stats["us_info"],
        stats["news"],
        stats["policies"],
    )
    return stats


def run_analysis(logger):
    """分析模式 - 技术面+基本面+个股新闻情绪"""
    logger.info("=" * 50)
    logger.info("开始分析")
    storage = DataStorage()

    tech = TechnicalAnalyzer()
    fund = FundamentalAnalyzer()
    sent = SentimentAnalyzer()
    sig = SignalEngine()
    sizer = PositionSizer()
    # 加载新闻数据
    news = storage.load_json("all_news.json", subdir="news") or []
    policies = storage.load_json("all_policies.json", subdir="policy") or []
    market_sentiment = sent.analyze_news_and_policies(news, policies)

    results = []

    # 分析A股
    for code, name in A_STOCK_WATCHLIST.items():
        try:
            logger.info(f"分析A股 {code} {name} ...")
            df = storage.load_csv(f"akshare_kline_{code}.csv", subdir="kline")
            if df is None or df.empty:
                logger.warning(f"A股 {code} 无数据，跳过")
                continue
            df = normalize_ohlcv(df, code, "stored-akshare")
            if df.empty:
                logger.warning(f"A股 {code} 数据无效，跳过")
                continue
            tech_df = tech.calculate_all(df)
            fund_data = storage.load_json(f"akshare_fundamental_{code}.json", subdir="fundamental")
            fund_score = fund.analyze(fund_data) if fund_data else {}

            # 个股新闻情绪
            stock_news_sentiment = sent.analyze_stock_sentiment(news, code)

            result = {
                "code": code,
                "name": name,
                "market": "A股",
                "technical": tech.get_latest_signals(tech_df),
                "fundamental": fund_score,
                "news_sentiment": stock_news_sentiment,
                "data_quality": analyze_data_quality(df, fund_data, "A股"),
                "chart_data": _build_chart_data(tech_df),
            }
            results.append(result)
        except Exception as e:
            logger.error(f"分析A股 {code} 失败: {e}")

    # 分析港股
    for code, name in HK_STOCK_WATCHLIST.items():
        try:
            logger.info(f"分析港股 {code} {name} ...")
            df = storage.load_csv(f"akshare_hk_kline_{code}.csv", subdir="kline")
            if df is None or df.empty:
                logger.warning(f"港股 {code} 无数据，跳过")
                continue
            df = normalize_ohlcv(df, code, "stored-akshare-hk")
            if df.empty:
                logger.warning(f"港股 {code} 数据无效，跳过")
                continue
            tech_df = tech.calculate_all(df)
            stock_news_sentiment = sent.analyze_stock_sentiment(news, code)

            result = {
                "code": code,
                "name": name,
                "market": "港股",
                "technical": tech.get_latest_signals(tech_df),
                "fundamental": fund.missing_result(),
                "news_sentiment": stock_news_sentiment,
                "data_quality": analyze_data_quality(df, None, "港股"),
                "chart_data": _build_chart_data(tech_df),
            }
            results.append(result)
        except Exception as e:
            logger.error(f"分析港股 {code} 失败: {e}")

    # 分析美股
    for ticker, name in US_STOCK_WATCHLIST.items():
        try:
            logger.info(f"分析美股 {ticker} {name} ...")
            df = storage.load_csv(f"yahoo_history_{ticker}.csv", subdir="history")
            if df is None or df.empty:
                logger.warning(f"美股 {ticker} 无数据，跳过")
                continue
            df = normalize_ohlcv(df, ticker, "stored-yahoo")
            if df.empty:
                logger.warning(f"美股 {ticker} 数据无效，跳过")
                continue
            tech_df = tech.calculate_all(df)
            info = storage.load_json(f"yahoo_info_{ticker}.json", subdir="info")
            fund_score = fund.analyze_us(info) if info else {}

            # 个股新闻情绪
            stock_news_sentiment = sent.analyze_stock_sentiment(news, ticker)

            result = {
                "code": ticker,
                "name": name,
                "market": "美股",
                "technical": tech.get_latest_signals(tech_df),
                "fundamental": fund_score,
                "news_sentiment": stock_news_sentiment,
                "data_quality": analyze_data_quality(df, info, "美股"),
                "chart_data": _build_chart_data(tech_df),
            }
            results.append(result)
        except Exception as e:
            logger.error(f"分析美股 {ticker} 失败: {e}")

    # 综合信号生成
    for r in results:
        try:
            # 将个股新闻情绪融入信号
            sentiment_override = r["news_sentiment"].get("sentiment_score", 0)
            sentiment_data = {"combined_score": sentiment_override, "symbolNewsScore": sentiment_override}
            r["signal"] = sig.generate_signal(r["technical"], r["fundamental"], sentiment_data)
            min_lot = 100 if r["market"] in {"A股", "港股"} else 1
            r["position_suggestion"] = (
                sizer.suggest(
                    float(r["technical"].get("close") or 0),
                    float(r["technical"].get("atr") or 0),
                    min_lot=min_lot,
                    symbol=r["code"],
                )
                if r["signal"].get("signal_direction") == "LONG"
                else None
            )
        except Exception as e:
            logger.error(f"生成信号失败 {r['code']}: {e}")
            r["signal"] = {}

    storage.save_snapshot_json(results, "analysis_results.json", subdir="analysis")
    storage.save_snapshot_json(market_sentiment, "market_sentiment.json", subdir="analysis")
    logger.info("分析完成")
    return results, market_sentiment


def run_report(logger, analysis_results=None, market_sentiment=None):
    """报告生成模式 - 生成每日总结报告"""
    logger.info("=" * 50)
    logger.info("开始生成报告")
    storage = DataStorage()

    if analysis_results is None:
        analysis_results = storage.load_json("analysis_results.json", subdir="analysis") or []
    if market_sentiment is None:
        market_sentiment = storage.load_json("market_sentiment.json", subdir="analysis") or {}

    # 加载新闻总结
    news_summary = storage.load_json("news_summary.json", subdir="news") or {}

    gen = ReportGenerator()
    report_path = gen.generate_daily_summary_report(analysis_results, news_summary, market_sentiment)
    logger.info(f"报告已生成: {report_path}")

    # 邮件提醒
    notifier = EmailNotifier()
    if notifier.is_configured():
        try:
            notifier.send_report_alert(report_path, analysis_results)
            logger.info("邮件提醒已发送")
        except Exception as e:
            logger.error(f"邮件提醒失败: {e}")
    return report_path


def run_news(logger):
    """纯新闻日报模式 - 只抓取新闻并生成日报，不涉及行情/基本面/交易信号"""
    logger.info("=" * 50)
    logger.info("开始新闻日报")
    storage = DataStorage()
    nf = NewsFetcher()
    try:
        news = nf.fetch_all_news(per_source_limit=20)
    except Exception as e:
        logger.error(f"抓取新闻失败: {e}")
        news = []

    if not news:
        cached = storage.load_json("all_news.json", subdir="news") or []
        if cached:
            logger.warning("本次未抓到新新闻，使用最近一次缓存数据生成日报")
            news = cached
        else:
            logger.error("没有可用的新闻数据，新闻日报未生成")
            return None

    translated = NewsTranslator().translate_news(news)
    if translated is not news:
        news = translated

    storage.save_snapshot_json(news, "all_news.json", subdir="news")
    news_summary = nf.generate_daily_summary(news)
    storage.save_snapshot_json(news_summary, "news_summary.json", subdir="news")
    market_sentiment = SentimentAnalyzer().analyze_news_and_policies(news, [])

    report_path = NewsReportGenerator().generate(news, news_summary, market_sentiment)
    logger.info(f"新闻日报已生成: {report_path}")

    pusher = WeChatPusher()
    if pusher.is_configured():
        txt_path = report_path.with_suffix(".txt")
        if txt_path.exists():
            content = txt_path.read_text(encoding="utf-8")
            pusher.send_text(content, title=f"每日新闻日报 {news_summary.get('date', '')}")
        else:
            logger.warning("未找到纯文本日报，跳过微信推送")
    return report_path


def run_backtest(logger):
    """使用已保存历史数据验证当前信号规则。"""
    logger.info("=" * 50)
    logger.info("开始回测")
    storage = DataStorage()
    backtester = DailyBacktester()
    jobs = (
        [(code, f"akshare_kline_{code}.csv", "kline", "A股", 100) for code in A_STOCK_WATCHLIST]
        + [(code, f"akshare_hk_kline_{code}.csv", "kline", "港股", 100) for code in HK_STOCK_WATCHLIST]
        + [(ticker, f"yahoo_history_{ticker}.csv", "history", "美股", 1) for ticker in US_STOCK_WATCHLIST]
    )

    results = []
    for code, filename, subdir, market, min_lot in jobs:
        try:
            df = storage.load_csv(filename, subdir=subdir)
            if df is None or df.empty:
                logger.warning(f"回测 {code} 无数据，跳过")
                continue
            result = backtester.run(df, symbol=code, market=market, min_lot=min_lot)
            if result["metrics"]["trade_count"] == 0:
                logger.info(f"{code} 回测期间未产生交易")
            else:
                logger.info(
                    f"{code} 回测完成: 交易{result['metrics']['trade_count']}次，"
                    f"收益{result['metrics']['total_return_pct']}%，"
                    f"回撤{result['metrics']['max_drawdown_pct']}%"
                )
            results.append(result)
        except Exception as exc:
            logger.error(f"回测 {code} 失败: {exc}")

    report_path = generate_backtest_report(results)
    logger.info(f"回测报告已生成: {report_path}")
    return report_path, len(results)


def run_full(logger):
    """全流程执行"""
    run_fetch(logger)
    results, sentiment = run_analysis(logger)
    run_report(logger, results, sentiment)
    logger.info("全流程执行完毕")


def dispatch_mode(mode: str, logger) -> None:
    """Run one pipeline and persist its lifecycle in SQLite."""
    tracker = RunTracker()
    with tracker.run(mode) as run:
        if mode == "fetch":
            stats = run_fetch(logger)
            run.set_metrics(**stats)
        elif mode == "analysis":
            results, _ = run_analysis(logger)
            run.set_metrics(analyzed_stocks=len(results))
        elif mode == "report":
            report_path = run_report(logger)
            run.set_metrics(report_path=str(report_path))
        elif mode == "news":
            report_path = run_news(logger)
            run.set_metrics(news_report=str(report_path) if report_path else "")
        elif mode == "backtest":
            report_path, strategy_count = run_backtest(logger)
            run.set_metrics(
                backtest_report=str(report_path),
                strategy_count=strategy_count,
            )
        else:
            stats = run_fetch(logger)
            results, sentiment = run_analysis(logger)
            report_path = run_report(logger, results, sentiment)
            run.set_metrics(
                **stats,
                analyzed_stocks=len(results),
                report_path=str(report_path),
            )
        run.log("INFO", f"{mode} 模式执行成功")


def dispatch_safely(mode: str, logger) -> None:
    try:
        dispatch_mode(mode, logger)
    except Exception:
        logger.exception("任务执行失败")


def main():
    parser = argparse.ArgumentParser(description="量化交易系统")
    parser.add_argument(
        "--mode",
        choices=["full", "fetch", "analysis", "report", "backtest", "news"],
        default="full",
        help="运行模式: full=全流程, fetch=只抓取数据, analysis=只分析, report=只生成报告, backtest=历史回测, news=纯新闻日报",
    )
    parser.add_argument(
        "--schedule",
        metavar="HH:MM",
        help="启用每日常驻调度，例如 09:00；Windows 生产环境仍建议使用任务计划程序",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="与 --schedule 一起使用时，先立即执行一次再进入等待",
    )
    args = parser.parse_args()

    logger = setup_logging()
    logger.info(f"运行模式: {args.mode}")

    if args.schedule:
        try:
            schedule.every().day.at(args.schedule).do(dispatch_safely, args.mode, logger)
        except schedule.ScheduleValueError as exc:
            parser.error(f"--schedule 时间格式无效: {exc}")
        logger.info(f"已启用每日 {args.schedule} 调度，常驻等待中")
        if args.run_now:
            dispatch_safely(args.mode, logger)
        try:
            while True:
                schedule.run_pending()
                time.sleep(30)
        except KeyboardInterrupt:
            logger.info("调度服务已手动停止")
    else:
        dispatch_safely(args.mode, logger)
        logger.info("程序结束")


if __name__ == "__main__":
    main()
