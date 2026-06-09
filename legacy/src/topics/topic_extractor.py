"""
Topic extraction module for StoryQuant.
Clusters news articles into topics using TF-IDF + KMeans.
Supports Korean and English text.
"""

import os
import re
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans


# ---------------------------------------------------------------------------
# Korean text handling
# ---------------------------------------------------------------------------

# Common Korean particles and postpositions to strip from tokens
_KO_PARTICLES = re.compile(
    r'(이|가|을|를|은|는|의|에|에서|으로|로|와|과|도|만|까지|부터|한테|에게|께서|서|랑|이랑)$'
)

# Korean stop words (particles, auxiliary verbs, common filler words)
KOREAN_STOP_WORDS = {
    "은", "는", "이", "가", "을", "를", "의", "에", "에서", "으로", "로",
    "와", "과", "도", "만", "까지", "부터", "위해", "대한", "통해", "따르면",
    "있다", "없다", "했다", "한다", "된다", "되다", "하는", "있는", "것으로",
    "것이", "관련", "대해", "합니다", "입니다", "했습니다", "됩니다", "있습니다",
    "없습니다", "하며", "하고", "이며", "이고", "또한", "하지만", "그러나",
    "그리고", "따라", "위한", "통한", "대한", "관한", "라고", "라는", "이라는",
    "이라고", "으로서", "으로써", "에서는", "에서도", "에도", "에는", "에만",
    "부터는", "까지는", "에서의", "에서가", "이후", "이전", "현재", "최근",
    "지난", "올해", "이번", "다음", "계속", "이미", "아직", "매우", "더욱",
    "가장", "함께", "모두", "각", "각각", "수", "것", "등", "및", "또",
    # --- KR newsroom boilerplate (bylines, datelines, formatting tags) ---
    "기자", "특파원", "취재기자", "논설위원", "전문기자",
    "포토", "사진", "영상", "그래픽", "인포그래픽", "표제",
    "단독", "속보", "종합", "전문", "특징주", "뉴스", "보도",
    "전했다", "밝혔다", "전한다", "밝혔습니다", "보도했다", "보도",
    "오전", "오후", "어제", "오늘", "내일", "이날", "당일",
    "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일",
    "1일", "2일", "3일", "4일", "5일", "6일", "7일", "8일", "9일", "10일",
    "11일", "12일", "13일", "14일", "15일", "16일", "17일", "18일", "19일", "20일",
    "21일", "22일", "23일", "24일", "25일", "26일", "27일", "28일", "29일", "30일", "31일",
    "1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월",
    # Quarter / period markers (dominate topic clusters when not filtered)
    "1분기", "2분기", "3분기", "4분기", "분기", "상반기", "하반기", "연간",
    # News-agency datelines
    "서울=연합뉴스", "서울", "연합뉴스", "인포맥스",
    # Generic finance verbs / fillers
    "발표", "공시", "예정", "계획", "전망", "예상", "추진", "검토", "결정",
    "확정", "체결", "추가", "출시", "공개", "진행", "진출", "운영",
    # Common quote markers
    "라며", "이라며", "면서", "이면서", "는데", "한다고", "있다고", "라고",
    # Generic stock/finance noise
    "주가", "종목", "코스피", "코스닥", "투자자", "시장", "기업", "회사",
}


def _contains_korean(text: str) -> bool:
    """Return True if text contains any Hangul character."""
    return bool(re.search(r'[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]', text))


def _tokenize_korean(text: str) -> list:
    """
    Simple regex-based Korean tokenizer.
    Splits on whitespace, strips trailing particles, removes single-char tokens
    and stop words.
    """
    tokens = []
    for word in text.split():
        # Strip non-Korean/non-alphanumeric characters from edges
        word = re.sub(r'^[^\w가-힣]+|[^\w가-힣]+$', '', word)
        if not word:
            continue
        # Strip common particles from the end
        stripped = _KO_PARTICLES.sub('', word)
        token = stripped if stripped else word
        # Skip single characters and stop words
        if len(token) <= 1:
            continue
        if token in KOREAN_STOP_WORDS:
            continue
        tokens.append(token)
    return tokens


def _preprocess_korean(text: str) -> str:
    """
    Preprocess text for TF-IDF.
    - Korean: tokenize with particle stripping, return space-joined tokens.
    - English: return as-is.
    """
    if not text or not _contains_korean(text):
        return text
    tokens = _tokenize_korean(text)
    return " ".join(tokens) if tokens else text


def _korean_tokenizer(text: str) -> list:
    """Custom tokenizer for TfidfVectorizer that handles Korean and English."""
    if _contains_korean(text):
        return _tokenize_korean(text)
    # Fallback: simple whitespace + punctuation split for English
    return re.findall(r'\b[a-zA-Z][a-zA-Z0-9]{1,}\b', text.lower())


def _safe_n_clusters(n_articles: int, n_topics: int) -> int:
    """Return a safe cluster count that never exceeds the number of articles."""
    return max(1, min(n_topics, n_articles))


def _recency_weights(timestamps: pd.Series) -> np.ndarray:
    """Linear recency weights: newest article gets weight 1.0, oldest gets ~0."""
    ts = pd.to_datetime(timestamps, errors="coerce", utc=True)
    ts_numeric = ts.values.astype("int64").astype(float)
    min_t, max_t = ts_numeric.min(), ts_numeric.max()
    if max_t == min_t:
        return np.ones(len(ts_numeric))
    weights = (ts_numeric - min_t) / (max_t - min_t)
    # Avoid zero weights so every article contributes
    return np.clip(weights, 0.05, 1.0)


def extract_topics(news_df: pd.DataFrame, n_topics: int = 5) -> pd.DataFrame:
    """
    Extract hot topics from a news DataFrame.

    Parameters
    ----------
    news_df : pd.DataFrame
        Columns required: timestamp, title, source, market, url, summary
    n_topics : int
        Desired number of topic clusters.

    Returns
    -------
    pd.DataFrame
        Columns: topic_id, topic_label, keywords, frequency,
                 momentum_score, novelty_score, market,
                 representative_headlines
    """
    if news_df is None or news_df.empty:
        return pd.DataFrame(columns=[
            "topic_id", "topic_label", "keywords", "frequency",
            "momentum_score", "novelty_score", "market",
            "representative_headlines",
        ])

    df = news_df.copy().reset_index(drop=True)

    # --- 1. Build text corpus ---
    title_col = df.get("title", pd.Series([""] * len(df))).fillna("")
    summary_col = df.get("summary", pd.Series([""] * len(df))).fillna("")
    raw_texts = (title_col + " " + summary_col).str.strip()
    # Preprocess Korean text before vectorization
    texts = raw_texts.apply(_preprocess_korean)

    # Auto-scale cluster count when corpus is large (≥40 articles → up to 12 topics).
    if len(df) >= 80:
        n_topics = max(n_topics, 12)
    elif len(df) >= 40:
        n_topics = max(n_topics, 8)
    n_clusters = _safe_n_clusters(len(df), n_topics)

    # --- 2. TF-IDF vectorization (Korean/English mixed) ---
    vectorizer = TfidfVectorizer(
        max_features=2000,
        tokenizer=_korean_tokenizer,
        token_pattern=None,
        ngram_range=(1, 2),
        min_df=2 if len(df) >= 20 else 1,
        max_df=0.6,
        sublinear_tf=True,
    )
    try:
        tfidf_matrix = vectorizer.fit_transform(texts)
    except ValueError:
        # All documents are empty after tokenization
        return pd.DataFrame(columns=[
            "topic_id", "topic_label", "keywords", "frequency",
            "momentum_score", "novelty_score", "market",
            "representative_headlines",
        ])

    feature_names = np.array(vectorizer.get_feature_names_out())

    # --- 3. KMeans clustering ---
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
    labels = km.fit_predict(tfidf_matrix)
    df["_cluster"] = labels

    # --- 4. Recency weights for momentum ---
    if "timestamp" in df.columns:
        weights = _recency_weights(df["timestamp"])
    else:
        weights = np.ones(len(df))

    # --- 5. Build per-topic rows ---
    # For novelty: use the cluster's centroid distance as a proxy.
    # Novelty = 1 / (1 + mean intra-cluster distance to centroid).
    # Higher = more novel (tight, unique cluster).
    centers = km.cluster_centers_  # shape (n_clusters, n_features)

    rows = []
    for cid in range(n_clusters):
        mask = df["_cluster"] == cid
        cluster_df = df[mask]
        cluster_idx = cluster_df.index.tolist()

        if cluster_df.empty:
            continue

        # Top keywords from cluster centroid
        centroid = centers[cid]
        top5_idx = centroid.argsort()[::-1][:5]
        top3_idx = top5_idx[:3]
        keywords = feature_names[top5_idx].tolist()
        topic_label = " / ".join(feature_names[top3_idx].tolist())

        # Frequency
        frequency = len(cluster_df)

        # Momentum: mean recency weight in cluster
        momentum_score = float(np.mean(weights[cluster_idx]))

        # Novelty: 1 / (1 + mean cosine distance to centroid within cluster)
        cluster_matrix = tfidf_matrix[cluster_idx]
        dists = np.linalg.norm(
            cluster_matrix.toarray() - centroid, axis=1
        )
        novelty_score = float(1.0 / (1.0 + dists.mean()))

        # Market: most common market tag in cluster
        if "market" in cluster_df.columns:
            market = cluster_df["market"].mode().iloc[0] if not cluster_df["market"].isna().all() else "unknown"
        else:
            market = "unknown"

        # Representative headlines: top-3 titles closest to centroid
        sorted_by_dist = np.argsort(dists)[:3]
        rep_indices = [cluster_idx[i] for i in sorted_by_dist]
        rep_headlines = df.loc[rep_indices, "title"].tolist() if "title" in df.columns else []

        rows.append({
            "topic_id": cid,
            "topic_label": topic_label,
            "keywords": keywords,
            "frequency": frequency,
            "momentum_score": round(momentum_score, 4),
            "novelty_score": round(novelty_score, 4),
            "market": market,
            "representative_headlines": rep_headlines,
        })

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("momentum_score", ascending=False).reset_index(drop=True)
    return result


def assign_topics_to_articles(news_df: pd.DataFrame, n_topics: int = 5) -> pd.DataFrame:
    """
    Return news_df with added topic_id and topic_label columns.

    Parameters
    ----------
    news_df : pd.DataFrame
    n_topics : int

    Returns
    -------
    pd.DataFrame
        Original columns + topic_id, topic_label
    """
    if news_df is None or news_df.empty:
        df = news_df.copy() if news_df is not None else pd.DataFrame()
        df["topic_id"] = pd.Series(dtype=int)
        df["topic_label"] = pd.Series(dtype=str)
        return df

    df = news_df.copy().reset_index(drop=True)
    n_clusters = _safe_n_clusters(len(df), n_topics)

    title_col = df.get("title", pd.Series([""] * len(df))).fillna("")
    summary_col = df.get("summary", pd.Series([""] * len(df))).fillna("")
    texts = (title_col + " " + summary_col).str.strip().apply(_preprocess_korean)

    vectorizer = TfidfVectorizer(
        max_features=2000,
        tokenizer=_korean_tokenizer,
        token_pattern=None,
        ngram_range=(1, 2),
        min_df=2 if len(df) >= 20 else 1,
        max_df=0.6,
        sublinear_tf=True,
    )
    try:
        tfidf_matrix = vectorizer.fit_transform(texts)
    except ValueError:
        df["topic_id"] = -1
        df["topic_label"] = "unknown"
        return df

    feature_names = np.array(vectorizer.get_feature_names_out())
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
    labels = km.fit_predict(tfidf_matrix)

    # Build label map: cluster_id -> "kw1 / kw2 / kw3"
    centers = km.cluster_centers_
    label_map = {}
    for cid in range(n_clusters):
        top3 = centers[cid].argsort()[::-1][:3]
        label_map[cid] = " / ".join(feature_names[top3].tolist())

    df["topic_id"] = labels
    df["topic_label"] = df["topic_id"].map(label_map)
    return df


def save_topics_csv(df: pd.DataFrame, data_dir: str = "data/topics") -> str:
    """
    Save a topics DataFrame to a timestamped CSV file.

    Parameters
    ----------
    df : pd.DataFrame
    data_dir : str
        Directory to write into (created if missing).

    Returns
    -------
    str
        Absolute path of the saved file.
    """
    os.makedirs(data_dir, exist_ok=True)
    now = datetime.now(timezone.utc)
    filename = now.strftime("topics_%Y%m%d_%H.csv")
    path = os.path.join(data_dir, filename)
    df.to_csv(path, index=False)
    print(f"Saved topics to {path}")
    return path


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sample_data = {
        "timestamp": pd.date_range("2026-03-31 08:00", periods=12, freq="30min"),
        "title": [
            "Fed signals interest rate cuts in 2026",
            "Federal Reserve holds rates steady amid inflation concerns",
            "Central bank policy outlook: dovish shift expected",
            "Apple earnings beat estimates on iPhone demand",
            "Tech stocks rally as Apple reports record revenue",
            "iPhone 17 demand drives Apple stock to all-time high",
            "Oil prices surge on OPEC production cut announcement",
            "Crude oil hits $90 as Middle East tensions escalate",
            "Energy sector rallies after OPEC supply reduction",
            "Bitcoin breaks $80,000 amid institutional buying",
            "Crypto market surges: Ethereum up 15% this week",
            "Digital assets gain as traditional banks face scrutiny",
        ],
        "summary": [
            "The Federal Reserve indicated it may cut interest rates multiple times this year.",
            "Despite inflation staying above target, the Fed chose to hold rates at 5.25%.",
            "Analysts expect a dovish pivot as growth slows across major economies.",
            "Apple Inc. reported quarterly earnings that exceeded Wall Street forecasts.",
            "Technology shares jumped after Apple posted stronger-than-expected results.",
            "Strong demand from Asia markets pushed Apple's quarterly revenue to new highs.",
            "OPEC members agreed to cut output by 1 million barrels per day.",
            "Oil futures rose sharply after a supply cut deal among major producers.",
            "Energy companies saw stock gains following OPEC's announcement.",
            "Bitcoin crossed the $80k mark for the first time since its previous peak.",
            "Ethereum and other altcoins followed Bitcoin's lead in the latest rally.",
            "Regulatory clarity and ETF inflows boosted the entire crypto ecosystem.",
        ],
        "source": ["Reuters", "Bloomberg", "FT"] * 4,
        "market": ["US_BONDS"] * 3 + ["US_TECH"] * 3 + ["ENERGY"] * 3 + ["CRYPTO"] * 3,
        "url": [f"https://example.com/article/{i}" for i in range(12)],
    }

    news_df = pd.DataFrame(sample_data)

    print("=== extract_topics ===")
    topics = extract_topics(news_df, n_topics=4)
    print(topics[["topic_id", "topic_label", "keywords", "frequency", "momentum_score", "novelty_score", "market"]].to_string())

    print("\n=== assign_topics_to_articles ===")
    tagged = assign_topics_to_articles(news_df, n_topics=4)
    print(tagged[["timestamp", "title", "topic_id", "topic_label"]].to_string())

    print("\n=== save_topics_csv ===")
    path = save_topics_csv(topics, data_dir="/tmp/storyquant_topics")
    print(f"File written: {path}")

    print("\n=== edge case: empty DataFrame ===")
    empty_result = extract_topics(pd.DataFrame())
    print(f"Empty result shape: {empty_result.shape}, columns: {list(empty_result.columns)}")

    print("\n=== edge case: 2 articles, n_topics=5 ===")
    tiny_df = news_df.head(2)
    tiny_result = extract_topics(tiny_df, n_topics=5)
    print(f"Tiny result shape: {tiny_result.shape}")
    print(tiny_result[["topic_id", "topic_label", "frequency"]].to_string())
