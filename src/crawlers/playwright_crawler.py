"""
playwright_crawler.py - Playwright-based crawlers for JS-rendered sites.

Crawls Coinness and CoinMarketCap news pages using headless Chromium.
These sites are SPAs that require JavaScript rendering.
"""

import logging
from datetime import datetime, timezone, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

_COLUMNS = ["timestamp", "title", "source", "market", "url", "summary", "source_type"]

# Shared browser instance (lazy init)
_browser = None
_playwright = None


def _get_browser():
    """Lazy-init a shared headless Chromium browser."""
    global _browser, _playwright
    if _browser is None or not _browser.is_connected():
        from playwright.sync_api import sync_playwright
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
        logger.info("Playwright browser launched")
    return _browser


def shutdown_browser():
    """Cleanly shut down the shared browser (call on app exit)."""
    global _browser, _playwright
    if _browser:
        try:
            _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright:
        try:
            _playwright.stop()
        except Exception:
            pass
        _playwright = None


# ---------------------------------------------------------------------------
# Coinness
# ---------------------------------------------------------------------------

def crawl_coinness(hours_back: int = 6) -> pd.DataFrame:
    """Crawl Coinness live feed headlines via Playwright.

    Returns a DataFrame with columns matching the standard article schema.
    """
    logger.info("Crawling Coinness (hours_back=%d)", hours_back)
    articles = []

    try:
        browser = _get_browser()
        page = browser.new_page()
        page.set_default_timeout(20000)

        page.goto("https://coinness.com", wait_until="domcontentloaded")
        page.wait_for_selector("[class*=BreakingNewsWrap]", timeout=15000)
        page.wait_for_timeout(2000)

        items = page.query_selector_all("[class*=BreakingNewsWrap]")
        logger.info("Coinness: found %d news items", len(items))

        now = datetime.now(tz=timezone.utc)
        today_str = now.strftime("%Y-%m-%d")

        for item in items:
            try:
                # Time block (HH:MM format)
                time_el = item.query_selector("[class*=TimeBlock]")
                time_text = time_el.inner_text().strip() if time_el else ""

                # Title with link
                title_el = item.query_selector("[class*=BreakingNewsTitle] a")
                if not title_el:
                    title_el = item.query_selector("[class*=BreakingNewsTitle]")
                title = title_el.inner_text().strip() if title_el else ""

                # URL
                link_el = item.query_selector("a[href*='/news/']")
                href = link_el.get_attribute("href") if link_el else ""
                if href and not href.startswith("http"):
                    href = f"https://coinness.com{href}"

                # Summary (content body)
                content_el = item.query_selector("[class*=BreakingNewsContents]")
                summary = content_el.inner_text().strip() if content_el else ""

                # Parse timestamp
                if time_text:
                    try:
                        ts = datetime.strptime(f"{today_str} {time_text}", "%Y-%m-%d %H:%M")
                        ts = ts.replace(tzinfo=timezone.utc)
                        # If parsed time is in the future, it's from yesterday
                        if ts > now:
                            ts -= timedelta(days=1)
                    except ValueError:
                        ts = now
                else:
                    ts = now

                cutoff = now - timedelta(hours=hours_back)
                if ts < cutoff:
                    continue

                if not title:
                    continue

                articles.append({
                    "timestamp": ts.isoformat(),
                    "title": title,
                    "source": "Coinness",
                    "market": "crypto",
                    "url": href,
                    "summary": summary[:500],
                    "source_type": "community",
                })
            except Exception as e:
                logger.debug("Coinness item parse error: %s", e)
                continue

        page.close()

    except Exception as e:
        logger.error("Coinness crawl failed: %s", e)

    df = pd.DataFrame(articles, columns=_COLUMNS) if articles else pd.DataFrame(columns=_COLUMNS)
    df = df.drop_duplicates(subset=["url"]).reset_index(drop=True)
    logger.info("Coinness: collected %d articles", len(df))
    return df


# ---------------------------------------------------------------------------
# CoinMarketCap
# ---------------------------------------------------------------------------

def crawl_coinmarketcap(hours_back: int = 6) -> pd.DataFrame:
    """Crawl CoinMarketCap headlines/news via Playwright.

    Returns a DataFrame with columns matching the standard article schema.
    """
    logger.info("Crawling CoinMarketCap News (hours_back=%d)", hours_back)
    articles = []

    try:
        browser = _get_browser()
        page = browser.new_page()
        page.set_default_timeout(20000)

        page.goto("https://coinmarketcap.com/headlines/news/", wait_until="domcontentloaded")
        page.wait_for_selector("[class*=uikit-row]", timeout=15000)
        page.wait_for_timeout(2000)

        # Scroll to load more items
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)

        rows = page.query_selector_all("[class*=uikit-row]")
        logger.info("CMC: found %d row elements", len(rows))

        now = datetime.now(tz=timezone.utc)
        today_str = now.strftime("%Y-%m-%d")

        for row in rows:
            try:
                # Find the news link
                link_el = row.query_selector("a[class*=cmc-link]")
                if not link_el:
                    continue

                href = link_el.get_attribute("href") or ""
                if not href or "/community/" not in href:
                    continue

                # Title from img alt or link text
                img_el = row.query_selector("img[alt]")
                title = img_el.get_attribute("alt") if img_el else ""
                if not title:
                    title = link_el.inner_text().strip()
                if not title:
                    continue

                # Time text (HH:MM format)
                time_el = row.query_selector("p[color*=neutral]")
                time_text = time_el.inner_text().strip() if time_el else ""

                # Parse timestamp
                if time_text and ":" in time_text:
                    try:
                        ts = datetime.strptime(f"{today_str} {time_text}", "%Y-%m-%d %H:%M")
                        ts = ts.replace(tzinfo=timezone.utc)
                        if ts > now:
                            ts -= timedelta(days=1)
                    except ValueError:
                        ts = now
                else:
                    ts = now

                cutoff = now - timedelta(hours=hours_back)
                if ts < cutoff:
                    continue

                # Summary from remaining text
                full_text = row.inner_text()
                summary_lines = [
                    line.strip() for line in full_text.split("\n")
                    if line.strip() and line.strip() != title and ":" not in line[:3]
                ]
                summary = " ".join(summary_lines)[:500]

                if not href.startswith("http"):
                    href = f"https://coinmarketcap.com{href}"

                articles.append({
                    "timestamp": ts.isoformat(),
                    "title": title,
                    "source": "CoinMarketCap",
                    "market": "crypto",
                    "url": href,
                    "summary": summary,
                    "source_type": "community",
                })
            except Exception as e:
                logger.debug("CMC item parse error: %s", e)
                continue

        page.close()

    except Exception as e:
        logger.error("CoinMarketCap crawl failed: %s", e)

    df = pd.DataFrame(articles, columns=_COLUMNS) if articles else pd.DataFrame(columns=_COLUMNS)
    df = df.drop_duplicates(subset=["url"]).reset_index(drop=True)
    logger.info("CoinMarketCap: collected %d articles", len(df))
    return df


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------

def crawl_all_playwright(hours_back: int = 6) -> pd.DataFrame:
    """Crawl all Playwright-based sources and return a combined DataFrame."""
    frames = []
    for crawl_fn in (crawl_coinness, crawl_coinmarketcap):
        try:
            df = crawl_fn(hours_back=hours_back)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            logger.error("Playwright crawl error: %s", e)

    if not frames:
        return pd.DataFrame(columns=_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["url"]).reset_index(drop=True)
    combined = combined.sort_values("timestamp", ascending=False).reset_index(drop=True)
    logger.info("Playwright total: %d articles", len(combined))
    return combined


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    df = crawl_all_playwright(hours_back=12)
    if not df.empty:
        print(f"\n=== {len(df)} articles ===")
        for source, count in df.groupby("source").size().items():
            print(f"  {source}: {count}")
        print()
        print(df[["timestamp", "source", "title"]].to_string(index=False))
    else:
        print("No articles collected.")
    shutdown_browser()
