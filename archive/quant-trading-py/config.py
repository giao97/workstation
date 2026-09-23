"""
量化交易 - 全局配置中心
支持 Node.js 版本兼容配置，支持自定义股票列表
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 项目根目录
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data_storage"
REPORT_DIR = BASE_DIR / "reports"
LOG_DIR = BASE_DIR / "logs"
TEMPLATE_DIR = BASE_DIR / "templates"

# 确保目录存在
for d in [DATA_DIR, REPORT_DIR, LOG_DIR, TEMPLATE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ==================== 股票关注列表 ====================
# A股关注列表 (代码: 名称)
A_STOCK_WATCHLIST = {
    "600519": "贵州茅台",
    "000858": "五粮液",
    "000333": "美的集团",
    "600036": "招商银行",
    "000002": "万科A",
    "002594": "比亚迪",
    "300750": "宁德时代",
    "600900": "长江电力",
    "601318": "中国平安",
    "600276": "恒瑞医药",
}

# 港股关注列表 (AKShare 使用 5 位数字代码)
HK_STOCK_WATCHLIST = {
    "9999.HK": "网易",
    "0700.HK": "腾讯控股",
    "9988.HK": "阿里巴巴",
    "3690.HK": "美团",
    "1810.HK": "小米集团",
    "2318.HK": "中国平安",
    "3888.HK": "金山软件",
}

# 美股关注列表 (Yahoo ticker: 名称)
US_STOCK_WATCHLIST = {
    "AAPL": "苹果",
    "MSFT": "微软",
    "GOOGL": "谷歌",
    "AMZN": "亚马逊",
    "TSLA": "特斯拉",
    "NVDA": "英伟达",
    "META": "Meta",
    "BABA": "阿里巴巴",
    "JD": "京东",
    "TCEHY": "腾讯控股",
    "PDD": "拼多多",
    "NIO": "蔚来",
    "XPEV": "小鹏汽车",
    "LI": "理想汽车",
    "COIN": "Coinbase",
    "PLTR": "Palantir",
}

# 个股别名映射 (用于新闻关联匹配)
STOCK_ALIASES = {
    "600519": ["贵州茅台", "茅台", "Moutai"],
    "000858": ["五粮液", "Wuliangye"],
    "000333": ["美的集团", "美的", "Midea"],
    "600036": ["招商银行", "招行"],
    "000002": ["万科A", "万科", "Vanke"],
    "002594": ["比亚迪", "BYD"],
    "300750": ["宁德时代", "CATL"],
    "600900": ["长江电力"],
    "601318": ["中国平安", "平安"],
    "600276": ["恒瑞医药", "恒瑞"],
    "9999.HK": ["网易", "NetEase"],
    "0700.HK": ["腾讯控股", "腾讯", "Tencent"],
    "9988.HK": ["阿里巴巴", "阿里", "Alibaba"],
    "3690.HK": ["美团", "Meituan"],
    "1810.HK": ["小米集团", "小米", "Xiaomi"],
    "3888.HK": ["金山软件", "金山"],
    "AAPL": ["苹果", "Apple", "iPhone"],
    "MSFT": ["微软", "Microsoft"],
    "GOOGL": ["谷歌", "Google", "Alphabet"],
    "AMZN": ["亚马逊", "Amazon"],
    "TSLA": ["特斯拉", "Tesla", "马斯克", "Musk"],
    "NVDA": ["英伟达", "NVIDIA", "黄仁勋"],
    "META": ["Meta", "Facebook", "脸书"],
    "BABA": ["阿里巴巴", "阿里", "Alibaba"],
    "JD": ["京东", "JD.com"],
    "TCEHY": ["腾讯控股", "腾讯", "Tencent"],
    "PDD": ["拼多多", "PDD"],
    "NIO": ["蔚来", "NIO"],
    "XPEV": ["小鹏汽车", "小鹏", "XPeng"],
    "LI": ["理想汽车", "理想", "Li Auto"],
    "COIN": ["Coinbase"],
    "PLTR": ["Palantir"],
}

# ==================== 技术指标参数 ====================
TECHNICAL_PARAMS = {
    "ma_periods": [5, 10, 20, 60, 120],
    "ema_periods": [12, 26],
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bollinger_period": 20,
    "bollinger_std": 2,
    "kdj_k_period": 9,
    "kdj_d_period": 3,
    "kdj_j_period": 3,
    "atr_period": 14,
    "volume_ma_periods": [5, 20],
    "obv_enabled": True,
}

# ==================== 信号阈值参数 ====================
SIGNAL_THRESHOLDS = {
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "bollinger_breakout": True,
    "volume_spike_ratio": 2.0,
    "trend_ma_short": 20,
    "trend_ma_long": 60,
    "stop_loss_pct": 0.08,
    "take_profit_pct": 0.20,
    "fundamental_min_score": 60,
}

# ==================== 回测与组合配置 ====================
BACKTEST_CONFIG = {
    "initial_capital": float(os.getenv("BACKTEST_INITIAL_CAPITAL", "100000")),
    "commission_rate": float(os.getenv("BACKTEST_COMMISSION_RATE", "0.0003")),
    "slippage_bps": float(os.getenv("BACKTEST_SLIPPAGE_BPS", "2")),
    "min_commission": float(os.getenv("BACKTEST_MIN_COMMISSION", "5")),
    "stop_loss_atr_multiplier": 2,
    "take_profit_atr_multiplier": 3,
    "warmup_days": 60,
    "t_plus_one": os.getenv("BACKTEST_T_PLUS_ONE", "1").lower() in {"1", "true", "yes"},
    "allow_short": os.getenv("BACKTEST_ALLOW_SHORT", "0").lower() in {"1", "true", "yes"},
    "risk_free_rate": float(os.getenv("BACKTEST_RISK_FREE_RATE", "0.02")),
    "trading_days_per_year": 252,
}

POSITION_SIZING_CONFIG = {
    "default_capital": float(os.getenv("POSITION_CAPITAL", "100000")),
    "risk_per_trade": float(os.getenv("POSITION_RISK_PER_TRADE", "0.01")),
    "max_position_pct": float(os.getenv("POSITION_MAX_PCT", "0.20")),
    "atr_stop_multiplier": float(os.getenv("POSITION_ATR_STOP_MULTIPLIER", "2.0")),
}

# ==================== 基本面权重 ====================
FUNDAMENTAL_WEIGHTS = {
    "valuation": 0.25,
    "quality": 0.25,
    "growth": 0.25,
    "risk": 0.15,
    "cashflow": 0.10,
}

# ==================== 情绪分析关键词 ====================
SENTIMENT_KEYWORDS = {
    "positive": [
        "大涨", "暴涨", "突破", "反弹", "回升", "业绩超预期", "利好",
        "增持", "回购", "分拆", "合作", "获批", "创新高", "bullish",
        "growth", "profit", "beat expectations", "dividend", "buyback",
        "surge", "rally", "upgrade", "outperform",
    ],
    "negative": [
        "大跌", "暴跌", "崩盘", "跌停", "破发", "业绩不及预期", "利空",
        "减持", "退市", "调查", "罚款", "亏损", "裁员", "bearish",
        "loss", "miss", "default", "investigation", "sell",
        "plunge", "crash", "downgrade", "underperform",
    ],
}

# 事件/人物关键词 (用于新闻重要性加权)
EVENT_KEYWORDS = {
    "high_impact": [
        "章建平", "巴菲特", "芒格", "索罗斯", "桥水",
        "特朗普", "Trump", "拜登", "Biden",
        "关税", "制裁", "贸易战", "关税战", "tariff", "sanction",
        "美联储", "Fed", "加息", "降息", "利率决议", "rate cut", "rate hike",
        "央行", "降准", "降息", "LPR", "MLF",
        "疫情", "pandemic", "战争", "war", "冲突", "conflict",
    ],
    "medium_impact": [
        "回购", "增持", "减持", "解禁", "定增", "配股",
        "buyback", "stake", "lock-up", "placement",
        "并购", "收购", "merger", "acquisition",
        "分红", "送转", "dividend", "split",
        "业绩预告", "earnings preview", "guidance",
    ],
}

# ==================== 邮件配置 ====================
EMAIL_CONFIG = {
    "smtp_host": os.getenv("SMTP_HOST", "smtp.qq.com"),
    "smtp_port": int(os.getenv("SMTP_PORT", "465")),
    "smtp_user": os.getenv("SMTP_USER", ""),
    "smtp_pass": os.getenv("SMTP_PASS", ""),
    "recipients": [r.strip() for r in os.getenv("ALERT_RECIPIENTS", "").split(",") if r.strip()],
    "enable_ssl": True,
}

# ==================== OpenAI 翻译配置 ====================
OPENAI_CONFIG = {
    "api_key": os.getenv("OPENAI_API_KEY", ""),
    "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    "base_url": os.getenv("OPENAI_BASE_URL", ""),
    "enabled": os.getenv("NEWS_TRANSLATE", "0").lower() in {"1", "true", "yes", "on"},
}

# ==================== 微信推送配置 ====================
WECHAT_PUSH_CONFIG = {
    "webhook_url": os.getenv("WECHAT_WEBHOOK_URL", ""),
    "serverchan_sendkey": os.getenv("SERVERCHAN_SENDKEY", ""),
    "max_text_chars": int(os.getenv("NEWS_PUSH_MAX_CHARS", "6000")),
}

# ==================== 官方新闻源配置 ====================
OFFICIAL_NEWS_CONFIG = {
    "newsapi_key": os.getenv("NEWSAPI_KEY", ""),
    "newsapi_language": os.getenv("NEWSAPI_LANGUAGE", "en"),
    "newsapi_category": os.getenv("NEWSAPI_CATEGORY", "business"),
    "tushare_token": os.getenv("TUSHARE_TOKEN", ""),
    "official_first": os.getenv("NEWS_OFFICIAL_FIRST", "1").lower() in {"1", "true", "yes", "on"},
}

# ==================== 数据源配置 ====================
DATA_SOURCE_CONFIG = {
    "yahoo": {
        "proxy": os.getenv("YAHOO_PROXY", None),
        "timeout": 30,
        "retry_times": 3,
    },
    "akshare": {
        "timeout": int(os.getenv("AKSHARE_TIMEOUT", "30")),
    },
    "news": {
        "rss_timeout": 15,
        "page_timeout": 20,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    },
    "policy": {
        "page_timeout": 20,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    },
}

# ==================== 报告配置 ====================
REPORT_CONFIG = {
    "output_dir": Path(os.getenv("REPORT_OUTPUT_DIR", REPORT_DIR)),
    "template_dir": Path(os.getenv("REPORT_TEMPLATE_DIR", TEMPLATE_DIR)),
    "max_news_items": 30,
    "max_per_stock_news": 8,
    "chart_dpi": 120,
    "chart_figsize": (12, 8),
    "default_period": "6mo",
}

# ==================== 日志配置 ====================
LOG_CONFIG = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
    "file": LOG_DIR / os.getenv("LOG_FILE", "quant_trading.log"),
    "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    "datefmt": "%Y-%m-%d %H:%M:%S",
}
