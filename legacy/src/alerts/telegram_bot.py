"""
Telegram alert system for StoryQuant.
Sends real-time alerts for price events, whale movements, and trading signals.

Setup:
1. Create a bot via @BotFather on Telegram
2. Get your chat ID via @userinfobot
3. export TELEGRAM_BOT_TOKEN=your_token
4. export TELEGRAM_CHAT_ID=your_chat_id
"""

import os
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def _get_config():
    return {
        "token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
    }

def telegram_available() -> bool:
    cfg = _get_config()
    return bool(cfg["token"] and cfg["chat_id"])

def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram bot API."""
    cfg = _get_config()
    if not cfg["token"] or not cfg["chat_id"]:
        return False

    url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
    payload = {
        "chat_id": cfg["chat_id"],
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        logger.warning("Telegram API error: %s %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.warning("Telegram send failed: %s", e)
        return False


def format_event_alert(event: dict, attribution: dict = None, historical: dict = None) -> str:
    """Format a price event as a Telegram alert message."""
    severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(event.get("severity", ""), "⚪")
    event_type = event.get("event_type", "")
    ticker = event.get("ticker", "?")
    ret = event.get("return_1h", 0)
    try:
        ret_str = f"{float(ret):+.2%}"
    except (TypeError, ValueError):
        ret_str = str(ret)

    lines = [
        f"{severity_icon} <b>{ticker} {event_type.upper()}</b> {ret_str}",
        f"⏰ {event.get('timestamp', '')}",
    ]

    if attribution:
        lines.append("")
        lines.append(f"📰 <b>원인:</b> {attribution.get('news_title', 'N/A')}")
        lines.append(f"   신뢰도: {attribution.get('confidence', 'N/A')} (score: {attribution.get('total_score', 0):.2f})")

    if historical:
        lines.append("")
        lines.append(f"📜 <b>과거 유사 이벤트:</b>")
        lines.append(f"   평균 후속 수익률: {historical.get('avg_next_return', 0):+.2%}")
        lines.append(f"   샘플: {historical.get('sample_count', 0)}건")

    lines.append(f"\n🤖 StoryQuant Alert")
    return "\n".join(lines)


def format_trade_alert(trade: dict, action: str = "open") -> str:
    """Format a paper trade alert."""
    if action == "open":
        emoji = "📈" if trade.get("direction") == "long" else "📉"
        return (
            f"{emoji} <b>NEW TRADE: {trade.get('ticker', '?')} {trade.get('direction', '').upper()}</b>\n"
            f"진입가: {trade.get('entry_price', 0):,.2f}\n"
            f"시그널: {trade.get('signal_type', '')}\n"
            f"🤖 StoryQuant Paper Trade"
        )
    else:
        pnl = trade.get("pnl_pct", 0)
        emoji = "✅" if pnl > 0 else "❌"
        return (
            f"{emoji} <b>TRADE CLOSED: {trade.get('ticker', '?')} {trade.get('direction', '').upper()}</b>\n"
            f"PnL: {pnl:+.2f}%\n"
            f"진입: {trade.get('entry_price', 0):,.2f} → 청산: {trade.get('exit_price', 0):,.2f}\n"
            f"🤖 StoryQuant Paper Trade"
        )


def format_hot_topic_alert(topic: dict, historical: dict = None) -> str:
    """Format a hot topic emergence as a proactive Telegram alert."""
    label = topic.get("topic_label", "?")
    momentum = topic.get("momentum_score", 0)
    novelty = topic.get("novelty_score", 0)
    article_count = topic.get("article_count", 0)

    # Determine urgency
    if novelty > 0.8:
        icon = "🆕"
        tag = "NEW TOPIC"
    elif momentum > 0.7:
        icon = "🔥"
        tag = "TRENDING"
    else:
        icon = "📊"
        tag = "HOT TOPIC"

    lines = [
        f"{icon} <b>{tag}: {label}</b>",
        f"모멘텀: {'█' * int(momentum * 10)}{'░' * (10 - int(momentum * 10))} {momentum:.0%}",
        f"신규도: {'█' * int(novelty * 10)}{'░' * (10 - int(novelty * 10))} {novelty:.0%}",
        f"관련 기사: {article_count}건",
    ]

    if historical:
        avg_ret = historical.get("avg_return", 0)
        hit = historical.get("hit_rate", 0)
        n = historical.get("sample_count", 0)
        direction = "📈" if avg_ret > 0 else "📉"
        lines.append("")
        lines.append(f"{direction} <b>과거 통계 (최근 30일):</b>")
        lines.append(f"   이 토픽 등장 후 24h 평균: {avg_ret:+.2%}")
        lines.append(f"   양의 수익률 비율: {hit:.0%} ({n}건)")

    lines.append(f"\n🤖 StoryQuant Signal")
    return "\n".join(lines)


def format_whale_alert_msg(whale: dict) -> str:
    """Format a whale transfer alert."""
    token = whale.get("token", "?")
    usd = whale.get("usd_value", 0)
    from_entity = whale.get("from_entity", "unknown")
    to_entity = whale.get("to_entity", "unknown")

    # Determine if it's exchange inflow/outflow
    exchanges = {"binance", "coinbase", "kraken", "bitfinex", "okx", "bybit"}
    from_is_exchange = any(ex in from_entity.lower() for ex in exchanges) if from_entity else False
    to_is_exchange = any(ex in to_entity.lower() for ex in exchanges) if to_entity else False

    if from_is_exchange and not to_is_exchange:
        icon = "📤"
        flow = "거래소 출금 (매집 시그널)"
    elif to_is_exchange and not from_is_exchange:
        icon = "📥"
        flow = "거래소 입금 (매도 시그널)"
    else:
        icon = "🐋"
        flow = "대형 이체"

    lines = [
        f"{icon} <b>WHALE: {token} ${usd/1e6:,.1f}M</b>",
        f"방향: {flow}",
        f"From: {from_entity}",
        f"To: {to_entity}",
        f"\n🤖 StoryQuant Alert",
    ]
    return "\n".join(lines)


def format_oi_alert(ticker: str, oi_change_pct: float, ls_ratio: float) -> str:
    """Format an OI alert."""
    direction = "⬆️" if oi_change_pct > 0 else "⬇️"
    return (
        f"{direction} <b>{ticker} OI {oi_change_pct:+.1f}%</b>\n"
        f"롱/숏 비율: {ls_ratio:.2f}\n"
        f"{'⚠️ 과매수 주의' if ls_ratio > 2.0 else '⚠️ 과매도 주의' if ls_ratio < 0.5 else ''}\n"
        f"🤖 StoryQuant Alert"
    )


def format_daily_summary(stats: dict) -> str:
    """Format a daily summary message."""
    return (
        f"📊 <b>StoryQuant 일일 요약</b>\n\n"
        f"📰 뉴스: {stats.get('articles', 0)}건\n"
        f"⚡ 이벤트: {stats.get('events', 0)}건\n"
        f"🔗 Attribution: {stats.get('attributions', 0)}건\n"
        f"📈 트레이드: {stats.get('trades_opened', 0)}건 진입 / {stats.get('trades_closed', 0)}건 청산\n"
        f"💰 PnL: {stats.get('total_pnl', 0):+.2f}%\n"
        f"🎯 승률: {stats.get('win_rate', 0):.1f}%\n"
    )
