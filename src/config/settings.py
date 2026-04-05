"""
StoryQuant v2 configuration.
Central settings for amure-db integration and polling intervals.
"""
import os

# ── amure-db graph API ──
AMURE_DB_URL = os.environ.get("AMURE_DB_URL", "http://localhost:8081")
AMURE_DB_TIMEOUT = 10.0

# ── SQLite (time-series only) ──
SQLITE_DB_PATH = os.environ.get("STORYQUANT_DB", "data/storyquant.db")

# ── Polling intervals (seconds) ──
INTERVAL_NEWS = 300          # 5 min
INTERVAL_PRICES = 900        # 15 min
INTERVAL_TWITTER = 600       # 10 min
INTERVAL_EXCHANGE = 600      # 10 min
INTERVAL_COMMUNITY = 600     # 10 min
INTERVAL_DERIVATIVES = 300   # 5 min
INTERVAL_WHALE = 900         # 15 min
INTERVAL_SENTIMENT = 300     # 5 min
INTERVAL_ATTRIBUTION = 300   # 5 min
INTERVAL_REASONING = 900     # 15 min
INTERVAL_NARRATOR = 600      # 10 min
INTERVAL_CROSSMARKET = 300   # 5 min
INTERVAL_ALERTS = 60         # 1 min

# ── Event detection thresholds ──
RETURN_ZSCORE_THRESHOLD = 2.0
VOLUME_SPIKE_THRESHOLD = 2.0

# ── Attribution ──
ATTRIBUTION_TOP_K = 10
ATTRIBUTION_TIME_DECAY_HOURS = 2.0
WHALE_TRANSFER_EVIDENCE_MIN_USD = 10_000_000  # $10M+

# ── Narrative lifecycle ──
NARRATIVE_STALE_HOURS = 24
NARRATIVE_MIN_EVIDENCE = 3

# ── API Keys ──
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ARKHAM_API_KEY = os.environ.get("ARKHAM_API_KEY", "")
WHALE_ALERT_API_KEY = os.environ.get("WHALE_ALERT_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
