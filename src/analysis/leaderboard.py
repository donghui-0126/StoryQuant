"""
leaderboard.py - Paper Trading Leaderboard for StoryQuant.

Computes and displays trading performance metrics:
  - Total PnL, win rate, profit factor
  - Per-ticker breakdown
  - Per-signal-type breakdown
  - Streak analysis
  - Monthly performance
  - Shareable leaderboard card
"""

import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Performance computation
# ---------------------------------------------------------------------------

def compute_performance(conn: sqlite3.Connection, days: int = 30) -> dict:
    """Compute comprehensive paper trading performance metrics."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    trades = pd.read_sql_query(
        """SELECT * FROM trades WHERE entry_time >= ? ORDER BY entry_time""",
        conn, params=[cutoff],
    )

    if trades.empty:
        return {"has_data": False, "total_trades": 0}

    closed = trades[trades["status"] == "closed"].copy()
    open_trades = trades[trades["status"] == "open"]

    # Compute PnL for closed trades
    if not closed.empty:
        closed["pnl_pct"] = closed.apply(
            lambda r: ((r["exit_price"] - r["entry_price"]) / r["entry_price"] * 100)
            if r["direction"] == "long"
            else ((r["entry_price"] - r["exit_price"]) / r["entry_price"] * 100),
            axis=1,
        )
    else:
        closed["pnl_pct"] = pd.Series(dtype=float)

    # --- Overall stats ---
    total_trades = len(trades)
    closed_trades = len(closed)
    open_count = len(open_trades)
    wins = len(closed[closed["pnl_pct"] > 0]) if not closed.empty else 0
    losses = len(closed[closed["pnl_pct"] <= 0]) if not closed.empty else 0
    win_rate = wins / closed_trades if closed_trades > 0 else 0

    total_pnl = closed["pnl_pct"].sum() if not closed.empty else 0
    avg_pnl = closed["pnl_pct"].mean() if not closed.empty else 0
    max_win = closed["pnl_pct"].max() if not closed.empty else 0
    max_loss = closed["pnl_pct"].min() if not closed.empty else 0

    # Profit factor
    gross_profit = closed[closed["pnl_pct"] > 0]["pnl_pct"].sum() if wins > 0 else 0
    gross_loss = abs(closed[closed["pnl_pct"] <= 0]["pnl_pct"].sum()) if losses > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

    # Streaks
    if not closed.empty:
        results = (closed["pnl_pct"] > 0).astype(int).tolist()
        max_win_streak = _max_streak(results, 1)
        max_loss_streak = _max_streak(results, 0)
    else:
        max_win_streak = max_loss_streak = 0

    # --- Per ticker ---
    ticker_stats = {}
    if not closed.empty:
        for ticker, group in closed.groupby("ticker"):
            w = (group["pnl_pct"] > 0).sum()
            ticker_stats[ticker] = {
                "trades": len(group),
                "win_rate": w / len(group) if len(group) > 0 else 0,
                "total_pnl": group["pnl_pct"].sum(),
                "avg_pnl": group["pnl_pct"].mean(),
                "best": group["pnl_pct"].max(),
                "worst": group["pnl_pct"].min(),
            }

    # --- Per signal type ---
    signal_stats = {}
    if not closed.empty and "signal_type" in closed.columns:
        for sig_type, group in closed.groupby("signal_type"):
            w = (group["pnl_pct"] > 0).sum()
            signal_stats[sig_type] = {
                "trades": len(group),
                "win_rate": w / len(group) if len(group) > 0 else 0,
                "total_pnl": group["pnl_pct"].sum(),
                "avg_pnl": group["pnl_pct"].mean(),
            }

    # --- Monthly breakdown ---
    monthly = {}
    if not closed.empty:
        closed["month"] = pd.to_datetime(closed["entry_time"]).dt.to_period("M").astype(str)
        for month, group in closed.groupby("month"):
            w = (group["pnl_pct"] > 0).sum()
            monthly[month] = {
                "trades": len(group),
                "pnl": group["pnl_pct"].sum(),
                "win_rate": w / len(group),
            }

    return {
        "has_data": True,
        "period_days": days,
        "total_trades": total_trades,
        "closed_trades": closed_trades,
        "open_trades": open_count,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
        "max_win": max_win,
        "max_loss": max_loss,
        "profit_factor": profit_factor,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "per_ticker": ticker_stats,
        "per_signal": signal_stats,
        "monthly": monthly,
    }


def _max_streak(results: list[int], target: int) -> int:
    """Find max consecutive occurrences of target in results."""
    max_s = current = 0
    for r in results:
        if r == target:
            current += 1
            max_s = max(max_s, current)
        else:
            current = 0
    return max_s


# ---------------------------------------------------------------------------
# Leaderboard formatting
# ---------------------------------------------------------------------------

def format_leaderboard_text(perf: dict) -> str:
    """Format performance as a text leaderboard."""
    if not perf.get("has_data"):
        return "No paper trading data yet. Run the system to generate signals."

    lines = [
        "═══════════════════════════════════════",
        "  StoryQuant Paper Trading Leaderboard",
        "═══════════════════════════════════════",
        "",
        f"  Period: Last {perf['period_days']} days",
        f"  Total Trades: {perf['total_trades']} ({perf['closed_trades']} closed, {perf['open_trades']} open)",
        "",
        f"  Total PnL:     {perf['total_pnl']:+.2f}%",
        f"  Win Rate:      {perf['win_rate']:.0%} ({perf['wins']}W / {perf['losses']}L)",
        f"  Avg PnL:       {perf['avg_pnl']:+.2f}%",
        f"  Profit Factor: {perf['profit_factor']:.2f}",
        f"  Best Trade:    {perf['max_win']:+.2f}%",
        f"  Worst Trade:   {perf['max_loss']:+.2f}%",
        f"  Win Streak:    {perf['max_win_streak']}  |  Loss Streak: {perf['max_loss_streak']}",
    ]

    if perf.get("per_ticker"):
        lines.extend(["", "  ─── Per Ticker ───"])
        for ticker, s in sorted(perf["per_ticker"].items(), key=lambda x: x[1]["total_pnl"], reverse=True):
            lines.append(
                f"  {ticker:<12} {s['trades']:>3} trades  "
                f"WR {s['win_rate']:.0%}  "
                f"PnL {s['total_pnl']:+.1f}%  "
                f"Avg {s['avg_pnl']:+.2f}%"
            )

    if perf.get("per_signal"):
        lines.extend(["", "  ─── Per Signal Type ───"])
        for sig, s in sorted(perf["per_signal"].items(), key=lambda x: x[1]["total_pnl"], reverse=True):
            lines.append(
                f"  {sig:<20} {s['trades']:>3} trades  "
                f"WR {s['win_rate']:.0%}  "
                f"PnL {s['total_pnl']:+.1f}%"
            )

    if perf.get("monthly"):
        lines.extend(["", "  ─── Monthly ───"])
        for month, s in sorted(perf["monthly"].items()):
            lines.append(
                f"  {month}  {s['trades']:>3} trades  "
                f"WR {s['win_rate']:.0%}  "
                f"PnL {s['pnl']:+.1f}%"
            )

    lines.append("")
    lines.append("═══════════════════════════════════════")
    return "\n".join(lines)


def format_leaderboard_telegram(perf: dict) -> str:
    """Format performance for Telegram."""
    if not perf.get("has_data"):
        return "📊 No paper trading data yet."

    pnl = perf["total_pnl"]
    icon = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"

    lines = [
        f"{icon} <b>StoryQuant Paper Trading</b>",
        f"📅 Last {perf['period_days']} days",
        "",
        f"💰 Total PnL: <b>{pnl:+.2f}%</b>",
        f"🎯 Win Rate: {perf['win_rate']:.0%} ({perf['wins']}W/{perf['losses']}L)",
        f"📊 Trades: {perf['closed_trades']} closed, {perf['open_trades']} open",
        f"📈 Best: {perf['max_win']:+.2f}%  📉 Worst: {perf['max_loss']:+.2f}%",
        f"⚡ Profit Factor: {perf['profit_factor']:.2f}",
    ]

    # Top ticker
    if perf.get("per_ticker"):
        best_ticker = max(perf["per_ticker"].items(), key=lambda x: x[1]["total_pnl"])
        lines.append(f"\n🏆 Best: {best_ticker[0]} ({best_ticker[1]['total_pnl']:+.1f}%)")

    lines.append("\n🤖 StoryQuant Leaderboard")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Leaderboard Card (PNG)
# ---------------------------------------------------------------------------

def generate_leaderboard_card(
    conn: sqlite3.Connection,
    days: int = 30,
    output_path: str = None,
) -> bytes:
    """Generate a shareable leaderboard card as PNG."""
    from PIL import Image, ImageDraw
    from src.analysis.viral_card import COLORS, _get_font, _draw_rounded_rect, CARD_WIDTH, CARD_PADDING

    perf = compute_performance(conn, days=days)

    card_height = 700
    img = Image.new("RGB", (CARD_WIDTH, card_height), COLORS["bg"])
    draw = ImageDraw.Draw(img)

    font_title = _get_font(28, bold=True)
    font_subtitle = _get_font(16)
    font_big = _get_font(36, bold=True)
    font_label = _get_font(14)
    font_body = _get_font(16)
    font_small = _get_font(13)
    font_footer = _get_font(12)

    y = CARD_PADDING

    # Header
    draw.text((CARD_PADDING, y), "StoryQuant", fill=COLORS["accent"], font=font_title)
    y += 38
    draw.text((CARD_PADDING, y), f"PAPER TRADING LEADERBOARD  |  Last {days} days", fill=COLORS["text"], font=font_subtitle)
    y += 30
    draw.line([(CARD_PADDING, y), (CARD_WIDTH - CARD_PADDING, y)], fill=COLORS["border"], width=2)
    y += 25

    if not perf.get("has_data"):
        draw.text((CARD_PADDING, y + 50), "No trading data yet.", fill=COLORS["text_dim"], font=font_body)
    else:
        # Big PnL number
        pnl = perf["total_pnl"]
        pnl_color = COLORS["green"] if pnl > 0 else COLORS["red"] if pnl < 0 else COLORS["text"]
        draw.text((CARD_PADDING, y), f"{pnl:+.2f}%", fill=pnl_color, font=font_big)
        draw.text((CARD_PADDING + 200, y + 10), "Total PnL", fill=COLORS["text_dim"], font=font_label)
        y += 55

        # Stats grid (2x3)
        stats_grid = [
            (f"{perf['win_rate']:.0%}", "Win Rate"),
            (f"{perf['closed_trades']}", "Trades"),
            (f"{perf['profit_factor']:.2f}", "Profit Factor"),
            (f"{perf['max_win']:+.1f}%", "Best Trade"),
            (f"{perf['max_loss']:+.1f}%", "Worst Trade"),
            (f"{perf['max_win_streak']}", "Win Streak"),
        ]
        col_width = (CARD_WIDTH - CARD_PADDING * 2) // 3
        for i, (value, label) in enumerate(stats_grid):
            col = i % 3
            row = i // 3
            x = CARD_PADDING + col * col_width
            sy = y + row * 60

            val_color = COLORS["text"]
            if "Best" in label:
                val_color = COLORS["green"]
            elif "Worst" in label:
                val_color = COLORS["red"]

            draw.text((x, sy), value, fill=val_color, font=font_body)
            draw.text((x, sy + 22), label, fill=COLORS["text_dim"], font=font_small)

        y += 135

        # Per-ticker table
        draw.line([(CARD_PADDING, y), (CARD_WIDTH - CARD_PADDING, y)], fill=COLORS["border"], width=1)
        y += 15
        draw.text((CARD_PADDING, y), "PER TICKER", fill=COLORS["text"], font=_get_font(18, bold=True))
        y += 30

        # Table header
        cols = [CARD_PADDING, 160, 280, 400, 530, 660]
        for col, header in zip(cols, ["Ticker", "Trades", "Win Rate", "PnL", "Best", "Worst"]):
            draw.text((col, y), header, fill=COLORS["text_dim"], font=font_small)
        y += 25

        if perf.get("per_ticker"):
            sorted_tickers = sorted(perf["per_ticker"].items(), key=lambda x: x[1]["total_pnl"], reverse=True)
            for ticker, s in sorted_tickers[:8]:
                pnl_color = COLORS["green"] if s["total_pnl"] > 0 else COLORS["red"]
                draw.text((cols[0], y), ticker, fill=COLORS["text"], font=font_body)
                draw.text((cols[1], y), str(s["trades"]), fill=COLORS["text"], font=font_body)
                draw.text((cols[2], y), f"{s['win_rate']:.0%}", fill=COLORS["text"], font=font_body)
                draw.text((cols[3], y), f"{s['total_pnl']:+.1f}%", fill=pnl_color, font=font_body)
                draw.text((cols[4], y), f"{s['best']:+.1f}%", fill=COLORS["green"], font=font_body)
                draw.text((cols[5], y), f"{s['worst']:+.1f}%", fill=COLORS["red"], font=font_body)
                y += 30
        else:
            draw.text((CARD_PADDING + 20, y), "No closed trades yet", fill=COLORS["text_dim"], font=font_body)

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
        logger.info("Saved leaderboard card to %s", output_path)

    return png_bytes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    from src.db.schema import get_connection, init_db
    conn = get_connection()
    init_db(conn)

    perf = compute_performance(conn, days=90)
    print(format_leaderboard_text(perf))

    # Generate card
    card_path = "data/cards/leaderboard.png"
    generate_leaderboard_card(conn, days=90, output_path=card_path)
    print(f"\nCard saved to: {card_path}")

    # Telegram format
    print("\n--- Telegram Format ---")
    print(format_leaderboard_telegram(perf))

    conn.close()
