# kerno/skills/builtins/text.py
"""
Built-in text processing and NLP skills.

Design:
  - No heavy ML dependencies required for basic operations
  - Graceful degradation: if sklearn is unavailable, fall back to frequency
  - Always return structured objects (DataFrames, dicts), not raw strings
  - Rich displays for exploration
"""

_TEXT_SKILLS_CODE = r'''
import re as _re
from collections import Counter as _Counter

import pandas as pd
import numpy as np
from IPython.display import display as _display, HTML as _HTML

# A compact English stop-word set shared by the frequency helpers.
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "and", "but", "or",
    "nor", "not", "so", "yet", "both", "either", "neither", "each",
    "every", "all", "any", "few", "more", "most", "other", "some",
    "such", "no", "only", "own", "same", "than", "too", "very", "just",
    "that", "this", "these", "those", "it", "its", "i", "me", "my",
    "we", "our", "you", "your", "he", "him", "his", "she", "her",
    "they", "them", "their", "what", "which", "who", "whom", "when",
    "where", "why", "how", "if", "then", "else", "about", "up", "out",
}


def _as_text_list(texts):
    """Normalize a Series / list / ndarray of texts into a list of strings."""
    if isinstance(texts, pd.Series):
        return texts.dropna().astype(str).tolist()
    if isinstance(texts, np.ndarray):
        texts = texts.tolist()
    return [str(t) for t in texts if t is not None and not (isinstance(t, float) and np.isnan(t))]


def text_stats(series: pd.Series) -> dict:
    """
    Compute comprehensive statistics for a text column.

    Returns:
        dict with count, avg/min/max/median length, avg word count,
        unique ratio, null/empty counts, top words, and char distribution.
    """
    if not isinstance(series, pd.Series):
        series = pd.Series(series)

    s = series.dropna().astype(str)
    if len(s) == 0:
        print("⚠️  No non-null text values found")
        return {}

    lengths     = s.str.len()
    word_counts = s.str.split().str.len()

    all_words = []
    for text in s:
        all_words.extend(_re.findall(r'\b[a-zA-Z]{2,}\b', text.lower()))
    word_freq = _Counter(all_words).most_common(20)

    all_chars = ''.join(s.tolist())
    char_freq = _Counter(c for c in all_chars if c.isalpha()).most_common(10)

    result = {
        "count":             int(len(series)),
        "non_null":          int(len(s)),
        "null_count":        int(series.isna().sum()),
        "empty_count":       int((s.str.strip() == "").sum()),
        "avg_length":        round(float(lengths.mean()), 1),
        "min_length":        int(lengths.min()),
        "max_length":        int(lengths.max()),
        "median_length":     int(lengths.median()),
        "avg_words":         round(float(word_counts.mean()), 1),
        "unique_ratio":      round(float(s.nunique() / len(s)), 4),
        "top_words":         word_freq,
        "char_distribution": char_freq,
    }

    rows = [
        f"<tr><td>Records</td><td>{result['count']:,} ({result['non_null']:,} non-null)</td></tr>",
        f"<tr><td>Avg length</td><td>{result['avg_length']} chars / {result['avg_words']} words</td></tr>",
        f"<tr><td>Range</td><td>{result['min_length']} – {result['max_length']} chars</td></tr>",
        f"<tr><td>Unique ratio</td><td>{result['unique_ratio']:.1%}</td></tr>",
    ]
    _display(_HTML(
        "<table style='font-family:monospace;font-size:12px'>"
        "<tr><th colspan='2'>Text Statistics</th></tr>"
        + "".join(rows) + "</table>"
    ))

    if word_freq:
        top_str = ", ".join(f"{w}({c})" for w, c in word_freq[:10])
        print(f"Top words: {top_str}")

    return result


def word_frequencies(texts, top_n: int = 30, stop_words: bool = True) -> pd.DataFrame:
    """
    Compute a word-frequency table from a list/Series of texts.

    Returns:
        DataFrame with columns: word, count, frequency, rank
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    all_words = []
    for text in _as_text_list(texts):
        words = _re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())
        if stop_words:
            words = [w for w in words if w not in _STOP_WORDS]
        all_words.extend(words)

    freq  = _Counter(all_words).most_common(top_n)
    total = sum(c for _, c in freq) or 1

    df = pd.DataFrame(freq, columns=["word", "count"])
    if df.empty:
        print("⚠️  No words found in the provided texts")
        return df
    df["frequency"] = (df["count"] / total).round(4)
    df["rank"]      = range(1, len(df) + 1)

    fig, ax = plt.subplots(figsize=(10, max(4, len(df) * 0.3)))
    ax.barh(df["word"][::-1], df["count"][::-1], color="#0072B2", alpha=0.85)
    ax.set_xlabel("Count")
    ax.set_title(f"Top {len(df)} Words")
    fig.tight_layout()
    _display(fig)
    plt.close(fig)

    print(f"✓ {len(all_words):,} total words, {len(set(all_words)):,} unique")
    return df


def clean_text(
    series: pd.Series,
    lowercase:      bool = True,
    remove_html:    bool = True,
    remove_urls:    bool = True,
    remove_digits:  bool = False,
    strip_extra_ws: bool = True,
) -> pd.Series:
    """
    Clean a text column with configurable transformations.

    Returns a new Series; the original is never mutated.
    """
    s = series.copy().astype("object")
    original_nulls = int(s.isna().sum())

    if remove_html:
        s = s.str.replace(r'<[^>]+>', ' ', regex=True)
    if remove_urls:
        s = s.str.replace(r'https?://\S+', '', regex=True)
        s = s.str.replace(r'www\.\S+', '', regex=True)
    if remove_digits:
        s = s.str.replace(r'\d+', '', regex=True)
    if lowercase:
        s = s.str.lower()
    if strip_extra_ws:
        s = s.str.replace(r'\s+', ' ', regex=True).str.strip()

    cleaned_nulls = int(s.isna().sum())
    print(f"✓ Cleaned {len(s):,} texts")
    print(f"  Nulls: {original_nulls} → {cleaned_nulls}")
    if remove_html:
        print("  HTML tags removed")
    if remove_urls:
        print("  URLs removed")
    return s


def ngrams(texts, n: int = 2, top_k: int = 20) -> pd.DataFrame:
    """
    Extract n-grams from a collection of texts.

    Args:
        n: N-gram size (2 = bigrams, 3 = trigrams)
    Returns:
        DataFrame with columns: ngram, count
    """
    if n < 1:
        raise ValueError("n must be >= 1")

    grams = []
    for text in _as_text_list(texts):
        words = _re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())
        grams.extend(
            ' '.join(words[i:i + n])
            for i in range(len(words) - n + 1)
        )

    freq = _Counter(grams).most_common(top_k)
    df   = pd.DataFrame(freq, columns=["ngram", "count"])

    print(f"✓ Top {len(df)} {n}-grams:")
    for _, row in df.head(10).iterrows():
        print(f"  {row['count']:>5}  {row['ngram']}")
    return df


def sentiment_score(series: pd.Series) -> pd.DataFrame:
    """
    Rule-based sentiment scoring (no ML dependencies).

    Returns a DataFrame with: text_preview, score (-1..1), label,
    pos_words, neg_words.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    positive_words = {
        "good", "great", "excellent", "amazing", "wonderful", "fantastic",
        "love", "happy", "best", "perfect", "beautiful", "awesome",
        "brilliant", "outstanding", "superb", "delightful", "enjoy",
        "impressive", "remarkable", "pleasant", "satisfied", "recommend",
    }
    negative_words = {
        "bad", "terrible", "awful", "horrible", "worst", "hate",
        "disappointing", "poor", "ugly", "broken", "useless", "waste",
        "annoying", "frustrating", "pathetic", "dreadful", "miserable",
        "unacceptable", "disgusting", "regret", "refund", "complaint",
    }

    results = []
    for text in series.dropna():
        words = set(_re.findall(r'\b[a-z]+\b', str(text).lower()))
        pos   = len(words & positive_words)
        neg   = len(words & negative_words)
        total = pos + neg
        score = (pos - neg) / total if total > 0 else 0.0
        label = ("positive" if score > 0.1
                 else "negative" if score < -0.1
                 else "neutral")
        results.append({
            "text_preview": str(text)[:80],
            "score":        round(score, 3),
            "label":        label,
            "pos_words":    pos,
            "neg_words":    neg,
        })

    df = pd.DataFrame(results)
    if df.empty:
        print("⚠️  No texts to score")
        return df

    dist = df["label"].value_counts()
    print("Sentiment distribution:")
    for label, count in dist.items():
        print(f"  {label}: {count} ({count / len(df):.0%})")

    colors = {"positive": "#009E73", "neutral": "#E69F00", "negative": "#D55E00"}
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(dist.index, dist.values,
           color=[colors.get(l, "#999") for l in dist.index])
    ax.set_title("Sentiment Distribution")
    ax.set_ylabel("Count")
    fig.tight_layout()
    _display(fig)
    plt.close(fig)
    return df


def extract_emails(series: pd.Series) -> pd.DataFrame:
    """Extract email addresses from a text column."""
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails  = series.dropna().astype(str).str.findall(pattern).explode().dropna()
    df      = pd.DataFrame({"email": emails})
    print(f"✓ Found {len(df):,} email addresses ({df['email'].nunique()} unique)")
    return df


def extract_hashtags(series: pd.Series) -> pd.DataFrame:
    """Extract hashtags from a text column."""
    pattern  = r'#\w+'
    hashtags = series.dropna().astype(str).str.findall(pattern).explode().dropna()
    if len(hashtags) == 0:
        print("⚠️  No hashtags found")
        return pd.DataFrame(columns=["hashtag", "count"])
    freq = hashtags.value_counts().reset_index()
    freq.columns = ["hashtag", "count"]
    print(f"✓ Found {len(hashtags):,} hashtags ({freq.shape[0]} unique)")
    return freq


def extract_keywords(texts, top_n: int = 15, method: str = "frequency") -> pd.DataFrame:
    """
    Extract keywords from texts.

    method:
      - "tfidf":     use sklearn TfidfVectorizer
      - "frequency": simple word count (default fallback)
    """
    texts = _as_text_list(texts)
    if not texts:
        print("⚠️  No texts provided")
        return pd.DataFrame(columns=["keyword", "score"])

    if method == "tfidf":
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            vec    = TfidfVectorizer(max_features=max(top_n, 100),
                                     stop_words="english")
            tfidf  = vec.fit_transform(texts)
            terms  = vec.get_feature_names_out()
            scores = tfidf.mean(axis=0).A1
            df = pd.DataFrame({"keyword": terms, "score": scores})
            df = df.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
            print("✓ TF-IDF keywords extracted")
            return df
        except ImportError:
            print("⚠️  sklearn not available, falling back to frequency method")

    freq_df = word_frequencies(texts, top_n=top_n)
    if freq_df.empty:
        return freq_df
    return freq_df.rename(columns={"word": "keyword", "frequency": "score"})[["keyword", "score"]]
'''


def get_code() -> str:
    """Return the source code string for these skills."""
    return _TEXT_SKILLS_CODE
