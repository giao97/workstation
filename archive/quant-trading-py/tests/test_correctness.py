import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.adapters.daily_analysis_adapter import DailyAnalysisAdapter
from src.analysis.fundamental import FundamentalAnalyzer
from src.analysis.sentiment import SentimentAnalyzer
from src.analysis.signals import SignalEngine
from src.analysis.translator import NewsTranslator
from src.alert.push import WeChatPusher
from src.backtest.backtester import DailyBacktester
from src.data.fetch_akshare import AkshareDataFetcher
from src.data.fetch_yahoo import YahooDataFetcher
from src.data.fetch_news import NewsFetcher
from src.data.run_store import RunTracker
from src.data.schema import normalize_ohlcv
from src.data.storage import DataStorage
from src.report.generator import ReportGenerator
from src.report.backtest_report import generate_backtest_report
from src.report.news_report import NewsReportGenerator
from src.risk.portfolio import PositionSizer, PortfolioRisk


class CorrectnessTests(unittest.TestCase):
    def test_hk_symbol_normalization(self):
        self.assertEqual(AkshareDataFetcher.normalize_hk_symbol("0700.HK"), "00700")
        self.assertEqual(AkshareDataFetcher.normalize_hk_symbol("9999.HK"), "09999")

    def test_sina_stock_code_prefix(self):
        self.assertEqual(AkshareDataFetcher._sina_stock_code("600519"), "sh600519")
        self.assertEqual(AkshareDataFetcher._sina_stock_code("000001"), "sz000001")

    def test_akshare_kline_columns_are_normalized(self):
        source = pd.DataFrame(
            [
                {
                    "日期": "2026-01-01",
                    "开盘": "10",
                    "收盘": "11",
                    "最高": "12",
                    "最低": "9",
                    "成交量": "1000",
                }
            ]
        )
        result = AkshareDataFetcher._normalize_kline_columns(source)
        self.assertEqual(
            set(["date", "open", "close", "high", "low", "volume"]),
            set(["date", "open", "close", "high", "low", "volume"]).intersection(result.columns),
        )
        self.assertEqual(result.loc[0, "close"], 11.0)

    def test_sell_signal_does_not_build_inverted_long_levels(self):
        result = SignalEngine().generate_signal(
            {
                "close": 100.0,
                "atr": 2.0,
                "ma20": 99.0,
                "macd_death_cross": True,
                "rsi": 75,
            },
            {"total_score": 50, "flags": [], "risks": []},
            {"combined_score": 0},
        )
        self.assertIn("SELL", result["overall_signal"])
        self.assertEqual(result["signal_direction"], "EXIT")
        self.assertIsNone(result["stop_loss"])
        self.assertIsNone(result["take_profit"])
        self.assertIsNone(result["risk_reward_ratio"])

    def test_buy_signal_uses_long_risk_levels(self):
        result = SignalEngine().generate_signal(
            {
                "close": 100.0,
                "atr": 2.0,
                "ma20": 99.0,
                "macd_golden_cross": True,
                "rsi": 45,
            },
            {"total_score": 50, "flags": [], "risks": []},
            {"combined_score": 0},
        )
        self.assertIn("BUY", result["overall_signal"])
        self.assertEqual(result["signal_direction"], "LONG")
        self.assertEqual(result["stop_loss"], 96.0)
        self.assertEqual(result["take_profit"], 106.0)
        self.assertEqual(result["risk_reward_ratio"], 1.5)

    def test_low_priced_buy_signal_never_has_negative_stop_loss(self):
        result = SignalEngine().generate_signal(
            {
                "close": 0.0014,
                "atr": 0.02,
                "ma20": 0.0012,
                "macd_golden_cross": True,
                "rsi": 45,
            },
            {"total_score": 50, "flags": [], "risks": []},
            {"combined_score": 0},
        )
        self.assertGreater(result["stop_loss"], 0)
        self.assertGreater(result["take_profit"], result["stop_loss"])

    def test_high_fundamental_thresholds_are_applied(self):
        result = FundamentalAnalyzer().analyze({"pe_ttm": 80, "debt_ratio": 90})
        self.assertLessEqual(result["total_score"], 40)
        self.assertGreaterEqual(len(result["risks"]), 2)

    def test_report_handles_missing_technical_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            generator = ReportGenerator()
            generator.output_dir = Path(tmp)
            report_path = generator.generate_daily_summary_report(
                [
                    {
                        "code": "TEST",
                        "name": "Test",
                        "market": "A",
                        "technical": {"close": 10, "rsi": None, "ma20": None},
                        "fundamental": {"total_score": 50, "flags": [], "risks": []},
                        "signal": {
                            "overall_signal": "HOLD",
                            "stop_loss": None,
                            "take_profit": None,
                        },
                        "news_sentiment": {"news_count": 0},
                    }
                ],
                {},
                {},
            )
            html = report_path.read_text(encoding="utf-8")
            self.assertIn("RSI", html)
            self.assertIn("-", html)

    def test_daily_analysis_adapter_uses_internal_signal_keys(self):
        adapter = DailyAnalysisAdapter()
        converted = adapter.convert_to_daily_analysis_format(
            {
                "code": "AAPL",
                "name": "Apple",
                "market": "US",
                "technical": {"close": 100, "rsi": 50},
                "fundamental": {"total_score": 60, "rating": "OK", "raw": {}},
                "signal": {
                    "overall_signal": "BUY",
                    "overall_confidence": "MEDIUM",
                    "overall_reason": "test",
                    "stop_loss": 95,
                    "take_profit": 110,
                },
            }
        )
        self.assertEqual(converted["trading_signal"]["action"], "BUY")
        self.assertEqual(converted["trading_signal"]["stop_loss"], 95)
        self.assertEqual(converted["trading_signal"]["take_profit"], 110)

    def test_yahoo_history_is_normalized_to_lowercase_ohlcv(self):
        source = pd.DataFrame(
            [
                {
                    "Date": "2026-01-02",
                    "Open": 10,
                    "High": 12,
                    "Low": 9,
                    "Close": 11,
                    "Volume": 100,
                },
                {
                    "Date": "2026-01-01",
                    "Open": 9,
                    "High": 10,
                    "Low": 8,
                    "Close": 10,
                    "Volume": 80,
                },
            ]
        )
        normalized = normalize_ohlcv(source)
        self.assertEqual(
            set(["date", "open", "high", "low", "close", "volume"]),
            set(["date", "open", "high", "low", "close", "volume"]).intersection(normalized.columns),
        )
        self.assertEqual(normalized.iloc[0]["date"].strftime("%Y-%m-%d"), "2026-01-01")
        self.assertEqual(normalized.iloc[-1]["close"], 11.0)

    def test_normalizer_removes_nonpositive_adjusted_prices(self):
        source = pd.DataFrame(
            [
                {"Date": "2026-01-01", "Open": 10, "High": 11, "Low": 9, "Close": 10, "Volume": 100},
                {"Date": "2026-01-02", "Open": -1, "High": -0.5, "Low": -2, "Close": -1, "Volume": 100},
            ]
        )
        normalized = normalize_ohlcv(source)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized.iloc[0]["close"], 10.0)

    def test_yahoo_history_does_not_use_removed_proxy_kwarg(self):
        frame = pd.DataFrame(
            {
                "Date": ["2026-01-01"],
                "Open": [10],
                "High": [11],
                "Low": [9],
                "Close": [10],
                "Volume": [100],
            }
        )
        with patch("yfinance.Ticker.history", return_value=frame) as history:
            YahooDataFetcher().get_history("TEST", period="1mo")
        history.assert_called_once_with(period="1mo", interval="1d")

    def test_conflicting_strong_signals_resolve_to_hold(self):
        result = SignalEngine().generate_signal(
            {
                "close": 100.0,
                "atr": 2.0,
                "ma20": 99.0,
                "macd_golden_cross": True,
                "macd_death_cross": True,
                "rsi": 45,
            },
            {"total_score": 80, "flags": ["基本面优秀"], "risks": [], "available": True},
            {"combined_score": 0},
        )
        self.assertEqual(result["overall_signal"], "HOLD")
        self.assertIsNone(result["stop_loss"])

    def test_missing_fundamental_data_does_not_produce_default_buy_signal(self):
        result = SignalEngine().generate_signal(
            {
                "close": 100.0,
                "atr": 2.0,
                "ma20": 99.0,
                "macd_golden_cross": True,
                "rsi": 45,
            },
            FundamentalAnalyzer().missing_result(),
            {"combined_score": 0},
        )
        self.assertNotIn("基本面", str(result["signals"]))

    def test_sentiment_analysis_handles_negation(self):
        analyzer = SentimentAnalyzer()
        result = analyzer.analyze_item(
            {
                "title": "公司未亏损，也未创新高",
                "summary": "",
            }
        )
        self.assertEqual(result["sentiment_score"], 0)
        self.assertIn("亏损", result["matched_negative"])

    def test_news_seen_file_prevents_repeated_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen_file = Path(tmp) / "seen_news.json"
            fetcher = NewsFetcher(seen_file=seen_file)
            item = fetcher._normalize_news_item(
                {
                    "title": "腾讯控股发布业绩",
                    "summary": "港股腾讯增长",
                    "url": "",
                    "source": "测试",
                    "publish_time": "2026-08-21",
                }
            )
            self.assertIn("0700.HK", item["related_symbols"])
            self.assertNotIn("TCEHY", item["related_symbols"])
            self.assertTrue(item["news_id"])

            seen_ids = {item["news_id"]: "2026-08-21T00:00:00"}
            fetcher._save_seen_ids(seen_ids)
            self.assertEqual(fetcher._load_seen_ids(), seen_ids)

    def test_news_publish_time_accepts_numeric_strings(self):
        self.assertIsInstance(NewsFetcher._normalize_publish_time("1"), str)
        self.assertEqual(NewsFetcher._normalize_publish_time("not-a-time"), "not-a-time")

    def test_yahoo_rate_limit_backoff_is_longer(self):
        self.assertEqual(
            YahooDataFetcher._backoff_seconds(1, RuntimeError("Too Many Requests. Rate limited.")),
            5.0,
        )

    def test_storage_snapshot_and_run_history_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "data"
            storage = DataStorage(base_dir=base)
            storage.save_snapshot_json({"value": 1}, "result.json", subdir="analysis")
            self.assertEqual(storage.load_json("result.json", subdir="analysis")["value"], 1)
            self.assertTrue(list((base / "snapshots" / "analysis").rglob("result.json.*.json")))

            tracker = RunTracker(db_path=Path(tmp) / "runs.sqlite")
            with tracker.run("test") as run:
                run.set_metrics(checked=2)
                run.log("INFO", "ok")
            latest = tracker.latest()
            self.assertEqual(latest["status"], "SUCCESS")
            self.assertEqual(latest["mode"], "test")

    def test_daily_backtester_returns_trade_metrics(self):
        dates = pd.date_range("2025-01-01", periods=130, freq="B")
        close = np.linspace(100, 150, len(dates)) + np.sin(np.arange(len(dates)) / 8) * 2
        frame = pd.DataFrame(
            {
                "date": dates,
                "open": close - 0.5,
                "high": close + 1.5,
                "low": close - 1.5,
                "close": close,
                "volume": 1_000_000,
            }
        )
        result = DailyBacktester(
            {
                "warmup_days": 60,
                "initial_capital": 100000,
                "min_commission": 5,
                "commission_rate": 0.0003,
                "slippage_bps": 2,
            }
        ).run(frame, symbol="TEST", market="US")
        self.assertGreaterEqual(result["metrics"]["trade_count"], 1)
        self.assertGreater(len(result["equity_curve"]), 0)
        self.assertIn("max_drawdown_pct", result["metrics"])

    def test_position_sizer_applies_risk_and_exposure_caps(self):
        suggestion = PositionSizer().suggest(price=100, atr=2, capital=100000, min_lot=1)
        self.assertEqual(suggestion["status"], "VALID")
        self.assertLessEqual(suggestion["notional"], 20000)
        self.assertEqual(suggestion["shares"], 200)

        summary = PortfolioRisk(capital=100000).summarize(
            [
                {"notional": 15000, "sector": "科技"},
                {"notional": 10000, "sector": "金融"},
            ]
        )
        self.assertEqual(summary["total_notional"], 25000)
        self.assertIn("科技", summary["sector_weights"])

    def test_daily_report_includes_chart_data_and_missing_fundamental_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            generator = ReportGenerator()
            generator.output_dir = Path(tmp)
            report_path = generator.generate_daily_summary_report(
                [
                    {
                        "code": "TEST",
                        "name": "Test",
                        "market": "US",
                        "technical": {"close": 10, "rsi": 50, "ma20": 9.8, "atr": 0.5},
                        "fundamental": FundamentalAnalyzer().missing_result(),
                        "signal": {
                            "overall_signal": "BUY",
                            "overall_confidence": "MEDIUM",
                            "stop_loss": 9,
                            "take_profit": 12,
                            "signal_direction": "LONG",
                        },
                        "position_suggestion": {
                            "status": "VALID",
                            "shares": 100,
                            "position_pct": 10,
                            "stop_loss": 9,
                        },
                        "data_quality": {
                            "confidence": "HIGH",
                            "ohlcv": {"latest_date": "2026-08-21", "rows": 200},
                            "issues": [],
                        },
                        "chart_data": [
                            {
                                "date": "2026-08-21",
                                "open": 9.8,
                                "high": 10.2,
                                "low": 9.7,
                                "close": 10,
                                "volume": 1000,
                                "ma20": 9.8,
                            }
                        ],
                        "news_sentiment": {"news_count": 0},
                    }
                ],
                {},
                {},
            )
            html = report_path.read_text(encoding="utf-8")
            self.assertIn("lightweight-charts", html)
            self.assertIn('id="chart-0"', html)
            self.assertIn("数据不足", html)
            self.assertIn("建议仓位", html)

    def test_backtest_report_is_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = generate_backtest_report(
                [
                    {
                        "symbol": "TEST",
                        "market": "US",
                        "period_start": "2025-01-01",
                        "period_end": "2025-12-31",
                        "metrics": {
                            "total_return_pct": 10,
                            "max_drawdown_pct": -3,
                            "sharpe_ratio": 1.1,
                            "trade_count": 2,
                            "win_rate_pct": 50,
                            "net_profit": 100,
                        },
                        "trades": [],
                        "equity_curve": [],
                    }
                ],
                output_dir=Path(tmp),
                date_str="2026-08-21",
            )
            self.assertTrue(report_path.exists())
            self.assertTrue(Path(tmp, "backtest", "backtest_2026-08-21.html").exists())

    def test_news_digest_report_is_generated(self):
        news = [
            {
                "title": "美联储维持利率不变",
                "summary": "美联储按兵不动",
                "url": "https://example.com/fed",
                "source": "东方财富",
                "category": "财经要闻",
                "publish_time": "2026-08-24 08:00:00",
                "news_id": "a",
                "related_symbols": [],
                "sentiment_score": 0,
                "impact_score": 3,
            },
            {
                "title": "茅台发布业绩预告",
                "summary": "贵州茅台业绩超预期",
                "url": "https://example.com/moutai",
                "source": "财联社",
                "category": "市场电报",
                "publish_time": "2026-08-24 09:00:00",
                "news_id": "b",
                "related_symbols": ["600519"],
                "sentiment_score": 2,
                "impact_score": 1,
            },
        ]
        news_summary = {
            "date": "2026-08-24",
            "total_news": 2,
            "global_headlines": [news[0]],
            "stock_summaries": {
                "600519": {
                    "news_count": 1,
                    "positive_count": 1,
                    "negative_count": 0,
                    "total_sentiment": 2,
                    "top_news": [news[1]],
                    "summary": "茅台发布业绩预告",
                }
            },
        }
        market_sentiment = {
            "overall": "偏乐观",
            "combined_score": 0.8,
            "news_score": 2.0,
            "policy_score": 0.0,
            "summary": "主要利好: 茅台发布业绩预告",
        }
        with tempfile.TemporaryDirectory() as tmp:
            generator = NewsReportGenerator()
            generator.output_dir = Path(tmp)
            html_path = generator.generate(news, news_summary, market_sentiment)
            self.assertTrue(html_path.exists())
            for suffix in (".html", ".md", ".json", ".txt"):
                self.assertTrue(Path(str(html_path).replace(".html", suffix)).exists())
            text = Path(str(html_path).replace(".html", ".txt")).read_text(encoding="utf-8")
            self.assertIn("每日新闻日报", text)
            self.assertIn("美联储维持利率不变", text)
            self.assertIn("茅台发布业绩预告", text)
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("每日新闻日报", html)
            self.assertNotIn("止损", html)

    def test_news_translator_skips_without_config(self):
        news = [{"title": "Apple earnings beat expectations", "news_id": "1"}]
        translator = NewsTranslator({"api_key": "", "enabled": True})
        self.assertIs(translator.translate_news(news), news)

    def test_news_translator_updates_english_items(self):
        class FakeCompletions:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                content = '[{"news_id": "1", "title": "苹果财报超预期", "summary": "公司发布强劲季度业绩"}]'
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        news = [
            {
                "title": "Apple earnings beat expectations",
                "summary": "Company reports strong quarter",
                "news_id": "1",
            }
        ]
        translator = NewsTranslator({"api_key": "sk-test", "enabled": True, "model": "gpt-4o-mini"}, client=client)
        result = translator.translate_news(news)
        self.assertEqual(result[0]["title"], "苹果财报超预期")
        self.assertEqual(result[0]["title_en"], "Apple earnings beat expectations")
        self.assertEqual(result[0]["summary"], "公司发布强劲季度业绩")

    def test_wechat_pusher_sends_to_wecom_webhook(self):
        with patch("src.alert.push.requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"errcode": 0}
            pusher = WeChatPusher(
                {
                    "webhook_url": "https://qyapi.weixin.qq.com/hook",
                    "serverchan_sendkey": "",
                    "max_text_chars": 6000,
                }
            )
            self.assertTrue(pusher.send_text("测试日报"))
            mock_post.assert_called_once()
            payload = mock_post.call_args.kwargs["json"]
            self.assertEqual(payload["msgtype"], "text")

    def test_wechat_pusher_sends_to_serverchan(self):
        with patch("src.alert.push.requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"code": 0}
            pusher = WeChatPusher(
                {
                    "webhook_url": "",
                    "serverchan_sendkey": "SCTKEY",
                    "max_text_chars": 6000,
                }
            )
            self.assertTrue(pusher.send_text("测试日报", title="每日新闻日报"))
            self.assertIn("https://sctapi.ftqq.com/SCTKEY.send", mock_post.call_args.args[0])

    def test_newsapi_fetcher_normalizes_items(self):
        fake_response = {
            "status": "ok",
            "totalResults": 1,
            "articles": [
                {
                    "source": {"name": "CNBC"},
                    "title": "Fed holds rates",
                    "description": "Central bank keeps policy unchanged.",
                    "url": "https://example.com/fed",
                    "publishedAt": "2026-08-25T00:00:00Z",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp, patch("src.data.fetch_news.requests.get") as mock_get:
            mock_get.return_value.json.return_value = fake_response
            fetcher = NewsFetcher(seen_file=Path(tmp) / "seen.json")
            fetcher.official["newsapi_key"] = "test-key"
            items = fetcher.fetch_newsapi(limit=2)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["title"], "Fed holds rates")
            self.assertEqual(items[0]["source"], "CNBC")
            self.assertEqual(items[0]["category"], "Global News")

    def test_tushare_fetcher_normalizes_items(self):
        class FakePro:
            def news(self, **kwargs):
                return pd.DataFrame(
                    [
                        {
                            "title": "A股大涨",
                            "content": "市场情绪回暖",
                            "datetime": "2026-08-25 09:30:00",
                            "src": "sina",
                        }
                    ]
                )

        with tempfile.TemporaryDirectory() as tmp:
            fetcher = NewsFetcher(seen_file=Path(tmp) / "seen.json")
            fetcher.official["tushare_token"] = "test-token"
            items = fetcher.fetch_tushare(limit=5, pro=FakePro())
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["title"], "A股大涨")
            self.assertIn("Tushare", items[0]["source"])

    def test_official_first_skips_scraping(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = NewsFetcher(seen_file=Path(tmp) / "seen.json")
            fetcher.official.update({"newsapi_key": "test-key", "tushare_token": "", "official_first": True})
            fetcher.fetch_newsapi = lambda limit=20: [
                {
                    "title": "Official item",
                    "summary": "",
                    "url": "",
                    "source": "NewsAPI",
                    "category": "Global News",
                    "publish_time": "",
                    "news_id": "official-1",
                    "related_symbols": [],
                    "sentiment_score": 0,
                    "impact_score": 1,
                }
            ]

            def fail(*args, **kwargs):
                raise AssertionError("scraper should not be called")

            for method in (
                "fetch_eastmoney",
                "fetch_cls",
                "fetch_sina_finance",
                "fetch_xueqiu_hots",
                "fetch_cnbc",
                "fetch_reuters",
                "fetch_yahoo_finance_news",
            ):
                setattr(fetcher, method, fail)
            items = fetcher.fetch_all_news(per_source_limit=2)
            self.assertEqual([item["title"] for item in items], ["Official item"])


if __name__ == "__main__":
    unittest.main()
