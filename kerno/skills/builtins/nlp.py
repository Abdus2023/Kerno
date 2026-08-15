# kerno/skills/builtins/nlp.py
"""
Built-in NLP skills beyond the lightweight regex text module.

These tools provide VADER sentiment, topic modeling, clustering, and
semantic search. Heavy imports are lazy so kernel startup stays fast.
"""

_NLP_SKILLS_CODE = r'''
import re as _re

import pandas as pd
import numpy as np
from IPython.display import display as _display, HTML as _HTML


def _ensure_vader():
    """Import and initialize VADER, downloading the lexicon if needed."""
    try:
        import nltk
        from nltk.sentiment import SentimentIntensityAnalyzer
    except ImportError as exc:
        raise ImportError("nltk is required. Install with: pip install nltk") from exc

    try:
        nltk.data.find("sentiment/vader_lexicon.zip")
    except LookupError:
        try:
            nltk.download("vader_lexicon", quiet=True)
        except Exception:
            pass
    return SentimentIntensityAnalyzer()


def analyze_sentiment(texts, model: str = "vader") -> pd.DataFrame:
    """
    Analyze sentiment using VADER with a small built-in lexicon fallback.

    Returns a DataFrame with text preview, pos/neu/neg/compound scores, and label.
    """
    if isinstance(texts, pd.Series):
        source = texts
    else:
        source = pd.Series(texts)

    rows = []
    try:
        sia = _ensure_vader()
        use_vader = True
    except Exception:
        use_vader = False
        positive = {
            "good", "great", "excellent", "amazing", "love", "best",
            "perfect", "happy", "wonderful", "fantastic",
        }
        negative = {
            "bad", "terrible", "awful", "horrible", "worst", "hate",
            "broken", "poor", "useless", "disappointing",
        }
        print("⚠️  NLTK/VADER unavailable; using lexicon fallback")

    for text in source:
        raw = "" if pd.isna(text) else str(text)
        if use_vader:
            scores = sia.polarity_scores(raw)
        else:
            words = set(_re.findall(r"\b[a-z]+\b", raw.lower()))
            pos = len(words & positive)
            neg = len(words & negative)
            total = pos + neg
            compound = (pos - neg) / total if total else 0.0
            scores = {
                "pos": pos / max(total, 1),
                "neg": neg / max(total, 1),
                "neu": 1 - (pos + neg) / max(len(words), 1),
                "compound": compound,
            }
        label = ("Positive" if scores["compound"] > 0.05
                 else "Negative" if scores["compound"] < -0.05
                 else "Neutral")
        rows.append({
            "text_preview": raw[:100],
            "pos": round(float(scores.get("pos", 0)), 4),
            "neu": round(float(scores.get("neu", 0)), 4),
            "neg": round(float(scores.get("neg", 0)), 4),
            "compound": round(float(scores.get("compound", 0)), 4),
            "label": label,
        })

    df = pd.DataFrame(rows)
    _display(_HTML("<b>Sentiment distribution</b>"))
    _display(df["label"].value_counts().to_frame("count"))
    return df


def topic_model(texts, n_topics: int = 5, max_features: int = 1000) -> dict:
    """
    Fit an LDA topic model with CountVectorizer.

    Returns {"model", "vectorizer", "topics", "top_words"} and prints the
    top words per topic.
    """
    from sklearn.feature_extraction.text import CountVectorizer
    from sklearn.decomposition import LatentDirichletAllocation

    clean_texts = [str(t) for t in texts if not pd.isna(t)]
    if len(clean_texts) < n_topics:
        raise ValueError("Need at least as many documents as topics")

    vectorizer = CountVectorizer(max_features=max_features, stop_words="english")
    dtm = vectorizer.fit_transform(clean_texts)
    lda = LatentDirichletAllocation(n_components=n_topics, random_state=42)
    lda.fit(dtm)

    terms = vectorizer.get_feature_names_out()
    topics = {}
    top_words = []
    for i, topic_weights in enumerate(lda.components_):
        words = [terms[j] for j in topic_weights.argsort()[:-11:-1]]
        topics[f"Topic_{i+1}"] = words
        top_words.append({"topic": f"Topic_{i+1}", "top_words": ", ".join(words)})
        print(f"Topic {i+1}: {', '.join(words)}")

    return {
        "model": lda,
        "vectorizer": vectorizer,
        "topics": topics,
        "top_words": pd.DataFrame(top_words),
    }


def cluster_documents(texts, n_clusters: int = 5) -> pd.Series:
    """
    Cluster documents using TF-IDF + KMeans.

    Returns a Series of cluster labels.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.cluster import KMeans

    series = pd.Series(texts).fillna("").astype(str)
    vectorizer = TfidfVectorizer(stop_words="english", max_features=10000)
    matrix = vectorizer.fit_transform(series)
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(matrix)
    result = pd.Series(labels, index=series.index, name="cluster")

    terms = vectorizer.get_feature_names_out()
    print(f"✓ Clustered {len(series)} texts into {n_clusters} groups")
    for i, centroid in enumerate(km.cluster_centers_):
        top_terms = [terms[j] for j in centroid.argsort()[:-6:-1]]
        print(f"  Cluster {i} ({int((result == i).sum())} items): {', '.join(top_terms)}")
    return result


def semantic_search_tfidf(query: str, documents, top_k: int = 5) -> pd.DataFrame:
    """
    Local semantic search via TF-IDF cosine similarity.

    Useful when an embedding API is unavailable.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    docs = [str(doc) for doc in documents if not pd.isna(doc)]
    if not docs:
        return pd.DataFrame(columns=["document", "similarity"])

    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform(docs + [query])
    similarities = cosine_similarity(matrix[-1], matrix[:-1]).ravel()
    df = pd.DataFrame({"document": docs, "similarity": similarities})
    df = df.sort_values("similarity", ascending=False).head(top_k).reset_index(drop=True)
    _display(df.style.format({"similarity": "{:.4f}"}))
    return df
'''


def get_code() -> str:
    return _NLP_SKILLS_CODE
