"""
viral_card.py - Generate shareable viral cards for StoryQuant.

Creates PNG image cards summarizing:
  1. Weekly Top 5 Catalysts
  2. Best/Worst signal performance
  3. Cross-market signals
  4. Daily market summary

Cards are designed for sharing on Telegram, Twitter, Discord.
"""

import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from io import BytesIO

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color scheme (dark theme)
# ---------------------------------------------------------------------------

COLORS = {
    "bg": (15, 15, 25),
    "card_bg": (25, 28, 42),
    "text": (230, 230, 240),
    "text_dim": (140, 145, 165),
    "accent": (88, 166, 255),
    "green": (46, 204, 113),
    "red": (231, 76, 60),
    "gold": (255, 193, 37),
    "silver": (192, 192, 210),
    "bronze": (205, 127, 50),
    "border": (55, 60, 80),
}

CARD_WIDTH = 800
CARD_PADDING = 40


def _get_font(size: int, bold: bool = False):
    """Get a font, falling back to default if custom fonts unavailable."""
    from PIL import ImageFont
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _draw_rounded_rect(draw, xy, radius, fill, outline=None):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline)


# ---------------------------------------------------------------------------
# Card: Weekly Top Catalysts
# ---------------------------------------------------------------------------

def generate_top_catalysts_card(
    conn: sqlite3.Connection,
    days: int = 7,
    output_path: str = None,
) -> bytes:
    """Generate a 'Top 5 Catalysts This Week' viral card.

    Returns PNG bytes. Optionally saves to output_path.
    """
    from PIL import Image, ImageDraw

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Get top events with attributions
    sql = """
        SELECT
            e.ticker,
            e.event_type,
            e.return_1h,
            e.severity,
            e.timestamp,
            ar.title as news_title,
            a.total_score
        FROM events e
        JOIN attributions a ON a.event_id = e.id AND a.rank = 1
        JOIN articles ar ON a.article_id = ar.id
        WHERE e.timestamp >= ?
          AND e.event_type IN ('surge', 'crash')
          AND e.severity IN ('high', 'medium')
        ORDER BY ABS(e.return_1h) DESC
        LIMIT 5
    """
    try:
        df = pd.read_sql_query(sql, conn, params=[cutoff])
    except Exception:
        df = pd.DataFrame()

    # Compute card height
    item_height = 95
    header_height = 140
    footer_height = 80
    card_height = header_height + max(len(df), 1) * item_height + footer_height + CARD_PADDING * 2

    img = Image.new("RGB", (CARD_WIDTH, card_height), COLORS["bg"])
    draw = ImageDraw.Draw(img)

    font_title = _get_font(28, bold=True)
    font_subtitle = _get_font(16)
    font_item_title = _get_font(18, bold=True)
    font_item_body = _get_font(14)
    font_pct = _get_font(24, bold=True)
    font_footer = _get_font(12)

    y = CARD_PADDING

    # Header
    draw.text((CARD_PADDING, y), "StoryQuant", fill=COLORS["accent"], font=font_title)
    y += 38
    period_str = f"Last {days} days"
    draw.text((CARD_PADDING, y), f"TOP 5 CATALYSTS  |  {period_str}", fill=COLORS["text"], font=font_subtitle)
    y += 30

    # Divider
    draw.line([(CARD_PADDING, y), (CARD_WIDTH - CARD_PADDING, y)], fill=COLORS["border"], width=2)
    y += 20

    if df.empty:
        draw.text((CARD_PADDING, y + 40), "No significant events detected yet.", fill=COLORS["text_dim"], font=font_item_body)
    else:
        rank_colors = [COLORS["gold"], COLORS["silver"], COLORS["bronze"], COLORS["text_dim"], COLORS["text_dim"]]

        for i, (_, row) in enumerate(df.iterrows()):
            card_y = y + i * item_height

            # Rank badge
            _draw_rounded_rect(draw, (CARD_PADDING, card_y, CARD_PADDING + 36, card_y + 36), radius=8, fill=rank_colors[i])
            draw.text((CARD_PADDING + 12, card_y + 6), str(i + 1), fill=COLORS["bg"], font=font_item_title)

            # Ticker + event type
            ticker = row.get("ticker", "?")
            event_type = row.get("event_type", "")
            icon = "▲" if event_type == "surge" else "▼"
            color = COLORS["green"] if event_type == "surge" else COLORS["red"]

            draw.text((CARD_PADDING + 50, card_y + 2), f"{icon} {ticker}", fill=color, font=font_item_title)

            # Return percentage
            ret = row.get("return_1h", 0)
            try:
                ret_str = f"{float(ret):+.1%}"
            except (TypeError, ValueError):
                ret_str = "N/A"
            draw.text((CARD_WIDTH - CARD_PADDING - 100, card_y + 2), ret_str, fill=color, font=font_pct)

            # News title (truncated)
            news = str(row.get("news_title", ""))[:70]
            if len(str(row.get("news_title", ""))) > 70:
                news += "..."
            draw.text((CARD_PADDING + 50, card_y + 28), news, fill=COLORS["text_dim"], font=font_item_body)

            # Timestamp
            ts = str(row.get("timestamp", ""))[:16]
            score = row.get("total_score", 0)
            try:
                meta = f"{ts}  |  confidence: {float(score):.0%}"
            except (TypeError, ValueError):
                meta = ts
            draw.text((CARD_PADDING + 50, card_y + 50), meta, fill=COLORS["border"], font=font_footer)

            # Separator
            if i < len(df) - 1:
                sep_y = card_y + item_height - 10
                draw.line([(CARD_PADDING + 50, sep_y), (CARD_WIDTH - CARD_PADDING, sep_y)], fill=COLORS["border"], width=1)

    # Footer
    footer_y = card_height - footer_height
    draw.line([(CARD_PADDING, footer_y), (CARD_WIDTH - CARD_PADDING, footer_y)], fill=COLORS["border"], width=2)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    draw.text((CARD_PADDING, footer_y + 15), f"Generated: {now_str}", fill=COLORS["text_dim"], font=font_footer)
    draw.text((CARD_WIDTH - CARD_PADDING - 200, footer_y + 15), "github.com/donghui-0126/StoryQuant", fill=COLORS["accent"], font=font_footer)

    # Save
    buf = BytesIO()
    img.save(buf, format="PNG", quality=95)
    png_bytes = buf.getvalue()

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(png_bytes)
        logger.info("Saved catalyst card to %s", output_path)

    return png_bytes


# ---------------------------------------------------------------------------
# Card: Signal Performance
# ---------------------------------------------------------------------------

def generate_signal_performance_card(
    conn: sqlite3.Connection,
    days: int = 30,
    output_path: str = None,
) -> bytes:
    """Generate a signal performance summary card with win rates and returns."""
    from PIL import Image, ImageDraw

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Get event stats per ticker
    sql = """
        SELECT
            e.ticker,
            e.event_type,
            COUNT(*) as count,
            AVG(e.return_1h) as avg_return
        FROM events e
        WHERE e.timestamp >= ? AND e.event_type IN ('surge', 'crash')
        GROUP BY e.ticker, e.event_type
        ORDER BY COUNT(*) DESC
    """
    try:
        df = pd.read_sql_query(sql, conn, params=[cutoff])
    except Exception:
        df = pd.DataFrame()

    # Build per-ticker summary
    tickers = df["ticker"].unique().tolist() if not df.empty else []

    row_height = 50
    header_height = 120
    table_header = 40
    footer_height = 60
    card_height = header_height + table_header + max(len(tickers), 1) * row_height + footer_height + CARD_PADDING * 2

    img = Image.new("RGB", (CARD_WIDTH, card_height), COLORS["bg"])
    draw = ImageDraw.Draw(img)

    font_title = _get_font(28, bold=True)
    font_subtitle = _get_font(16)
    font_header = _get_font(14, bold=True)
    font_body = _get_font(15)
    font_footer = _get_font(12)

    y = CARD_PADDING

    # Header
    draw.text((CARD_PADDING, y), "StoryQuant", fill=COLORS["accent"], font=font_title)
    y += 38
    draw.text((CARD_PADDING, y), f"SIGNAL PERFORMANCE  |  Last {days} days", fill=COLORS["text"], font=font_subtitle)
    y += 30
    draw.line([(CARD_PADDING, y), (CARD_WIDTH - CARD_PADDING, y)], fill=COLORS["border"], width=2)
    y += 15

    # Table header
    cols = [CARD_PADDING, 160, 280, 400, 530, 660]
    headers = ["Ticker", "Surges", "Crashes", "Avg Surge", "Avg Crash", "Net"]
    for col, header in zip(cols, headers):
        draw.text((col, y), header, fill=COLORS["text_dim"], font=font_header)
    y += table_header

    if df.empty:
        draw.text((CARD_PADDING, y + 20), "No data yet.", fill=COLORS["text_dim"], font=font_body)
    else:
        for ticker in tickers:
            t_data = df[df["ticker"] == ticker]
            surge = t_data[t_data["event_type"] == "surge"]
            crash = t_data[t_data["event_type"] == "crash"]

            surge_count = int(surge["count"].sum()) if not surge.empty else 0
            crash_count = int(crash["count"].sum()) if not crash.empty else 0
            surge_avg = float(surge["avg_return"].mean()) if not surge.empty else 0
            crash_avg = float(crash["avg_return"].mean()) if not crash.empty else 0
            net = surge_avg * surge_count + crash_avg * crash_count
            net_color = COLORS["green"] if net > 0 else COLORS["red"]

            draw.text((cols[0], y), ticker, fill=COLORS["text"], font=font_body)
            draw.text((cols[1], y), str(surge_count), fill=COLORS["green"], font=font_body)
            draw.text((cols[2], y), str(crash_count), fill=COLORS["red"], font=font_body)
            draw.text((cols[3], y), f"{surge_avg:+.2%}", fill=COLORS["green"], font=font_body)
            draw.text((cols[4], y), f"{crash_avg:+.2%}", fill=COLORS["red"], font=font_body)
            draw.text((cols[5], y), f"{net:+.3f}", fill=net_color, font=font_body)

            y += row_height

    # Footer
    footer_y = card_height - footer_height
    draw.line([(CARD_PADDING, footer_y), (CARD_WIDTH - CARD_PADDING, footer_y)], fill=COLORS["border"], width=2)
    draw.text((CARD_PADDING, footer_y + 10), datetime.now().strftime("%Y-%m-%d %H:%M UTC"), fill=COLORS["text_dim"], font=font_footer)
    draw.text((CARD_WIDTH - CARD_PADDING - 200, footer_y + 10), "github.com/donghui-0126/StoryQuant", fill=COLORS["accent"], font=font_footer)

    buf = BytesIO()
    img.save(buf, format="PNG", quality=95)
    png_bytes = buf.getvalue()

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(png_bytes)
        logger.info("Saved performance card to %s", output_path)

    return png_bytes


# ---------------------------------------------------------------------------
# Card: Market Summary (daily)
# ---------------------------------------------------------------------------

def generate_daily_summary_card(
    conn: sqlite3.Connection,
    output_path: str = None,
) -> bytes:
    """Generate a daily market summary card."""
    from PIL import Image, ImageDraw

    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    # Gather stats
    articles_count = conn.execute("SELECT COUNT(*) FROM articles WHERE published_at >= ?", [cutoff_24h]).fetchone()[0]
    events_count = conn.execute("SELECT COUNT(*) FROM events WHERE timestamp >= ? AND event_type IS NOT NULL", [cutoff_24h]).fetchone()[0]
    attr_count = conn.execute(
        "SELECT COUNT(*) FROM attributions a JOIN events e ON a.event_id = e.id WHERE e.timestamp >= ?",
        [cutoff_24h]
    ).fetchone()[0]

    # Top movers
    movers_sql = """
        SELECT ticker, event_type, return_1h, severity
        FROM events
        WHERE timestamp >= ? AND event_type IN ('surge', 'crash')
        ORDER BY ABS(return_1h) DESC
        LIMIT 5
    """
    movers = pd.read_sql_query(movers_sql, conn, params=[cutoff_24h])

    # Top topics
    topics_sql = """
        SELECT topic_label, momentum_score, frequency as article_count
        FROM topics
        WHERE created_at >= ?
        ORDER BY momentum_score DESC
        LIMIT 3
    """
    topics = pd.read_sql_query(topics_sql, conn, params=[cutoff_24h])

    card_height = 650
    img = Image.new("RGB", (CARD_WIDTH, card_height), COLORS["bg"])
    draw = ImageDraw.Draw(img)

    font_title = _get_font(28, bold=True)
    font_subtitle = _get_font(16)
    font_section = _get_font(18, bold=True)
    font_body = _get_font(15)
    font_small = _get_font(13)
    font_footer = _get_font(12)

    y = CARD_PADDING

    # Header
    draw.text((CARD_PADDING, y), "StoryQuant", fill=COLORS["accent"], font=font_title)
    y += 38
    today_str = datetime.now().strftime("%Y-%m-%d")
    draw.text((CARD_PADDING, y), f"DAILY MARKET SUMMARY  |  {today_str}", fill=COLORS["text"], font=font_subtitle)
    y += 30
    draw.line([(CARD_PADDING, y), (CARD_WIDTH - CARD_PADDING, y)], fill=COLORS["border"], width=2)
    y += 20

    # Stats row
    stats = [
        (f"{articles_count}", "Articles"),
        (f"{events_count}", "Events"),
        (f"{attr_count}", "Attributions"),
    ]
    stat_width = (CARD_WIDTH - CARD_PADDING * 2) // 3
    for i, (value, label) in enumerate(stats):
        x = CARD_PADDING + i * stat_width
        draw.text((x + 20, y), value, fill=COLORS["accent"], font=font_title)
        draw.text((x + 20, y + 35), label, fill=COLORS["text_dim"], font=font_small)
    y += 75

    # Top Movers
    draw.line([(CARD_PADDING, y), (CARD_WIDTH - CARD_PADDING, y)], fill=COLORS["border"], width=1)
    y += 15
    draw.text((CARD_PADDING, y), "TOP MOVERS", fill=COLORS["text"], font=font_section)
    y += 30

    if movers.empty:
        draw.text((CARD_PADDING + 20, y), "No significant moves today", fill=COLORS["text_dim"], font=font_body)
        y += 30
    else:
        for _, row in movers.iterrows():
            icon = "▲" if row["event_type"] == "surge" else "▼"
            color = COLORS["green"] if row["event_type"] == "surge" else COLORS["red"]
            ret = float(row["return_1h"])
            draw.text((CARD_PADDING + 20, y), f"{icon} {row['ticker']}", fill=color, font=font_body)
            draw.text((300, y), f"{ret:+.2%}", fill=color, font=font_body)
            draw.text((450, y), row["severity"], fill=COLORS["text_dim"], font=font_small)
            y += 28

    y += 15

    # Hot Topics
    draw.line([(CARD_PADDING, y), (CARD_WIDTH - CARD_PADDING, y)], fill=COLORS["border"], width=1)
    y += 15
    draw.text((CARD_PADDING, y), "HOT TOPICS", fill=COLORS["text"], font=font_section)
    y += 30

    if topics.empty:
        draw.text((CARD_PADDING + 20, y), "No trending topics", fill=COLORS["text_dim"], font=font_body)
    else:
        for _, row in topics.iterrows():
            label = str(row.get("topic_label", ""))[:50]
            momentum = float(row.get("momentum_score", 0))
            bar_width = int(momentum * 200)
            draw.text((CARD_PADDING + 20, y), label, fill=COLORS["text"], font=font_body)
            # Momentum bar
            bar_x = 450
            _draw_rounded_rect(draw, (bar_x, y + 3, bar_x + bar_width, y + 18), radius=4, fill=COLORS["accent"])
            draw.text((bar_x + bar_width + 10, y), f"{momentum:.0%}", fill=COLORS["text_dim"], font=font_small)
            y += 28

    # Footer
    footer_y = card_height - 50
    draw.line([(CARD_PADDING, footer_y), (CARD_WIDTH - CARD_PADDING, footer_y)], fill=COLORS["border"], width=2)
    draw.text((CARD_PADDING, footer_y + 10), datetime.now().strftime("%Y-%m-%d %H:%M UTC"), fill=COLORS["text_dim"], font=font_footer)
    draw.text((CARD_WIDTH - CARD_PADDING - 200, footer_y + 10), "github.com/donghui-0126/StoryQuant", fill=COLORS["accent"], font=font_footer)

    buf = BytesIO()
    img.save(buf, format="PNG", quality=95)
    png_bytes = buf.getvalue()

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(png_bytes)
        logger.info("Saved daily summary card to %s", output_path)

    return png_bytes


# ---------------------------------------------------------------------------
# Telegram integration
# ---------------------------------------------------------------------------

def send_card_to_telegram(png_bytes: bytes, caption: str = "") -> bool:
    """Send a card image to Telegram."""
    import os
    import requests

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    files = {"photo": ("storyquant_card.png", BytesIO(png_bytes), "image/png")}
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}

    try:
        resp = requests.post(url, files=files, data=data, timeout=30)
        return resp.status_code == 200
    except Exception as e:
        logger.warning("Failed to send card to Telegram: %s", e)
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    from src.db.schema import get_connection, init_db
    conn = get_connection()
    init_db(conn)

    output_dir = Path("data/cards")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Generating cards...")

    generate_top_catalysts_card(conn, days=30, output_path=str(output_dir / "top_catalysts.png"))
    print("  -> top_catalysts.png")

    generate_signal_performance_card(conn, days=30, output_path=str(output_dir / "signal_performance.png"))
    print("  -> signal_performance.png")

    generate_daily_summary_card(conn, output_path=str(output_dir / "daily_summary.png"))
    print("  -> daily_summary.png")

    print(f"\nCards saved to {output_dir}/")
    conn.close()
