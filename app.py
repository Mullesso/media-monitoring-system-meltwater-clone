"""
Main application file for the media monitoring system.

This Streamlit application continuously monitors news articles and press releases
from credible news sources based on user‑defined keywords.  It uses the
NewsAPI to retrieve recent articles and falls back to a Google News RSS feed
when no API key is provided.  Each article is scraped with ``newspaper3k`` to
collect the full text, publication date and other metadata.  Articles are then
ranked according to recency and the perceived authority of their source.  The
resulting list can be sorted by date, relevance or source credibility.

The ``NEWS_API_KEY`` must be stored as a secret when deploying to Streamlit
Cloud.  Locally you can set it in your environment or using a ``.streamlit``
secrets file (see README for details).

Author: Media Monitoring System
"""

import datetime
import os
import urllib.parse
from typing import Dict, List, Tuple

import pandas as pd
import requests
import streamlit as st
from newspaper import Article
import feedparser
import nltk

# -----------------------------------------------------------------------------
# Utility functions
#
# The following helper functions encapsulate the functionality used throughout
# the application: fetching news articles, scraping content and calculating
# prioritisation scores.  Keeping these functions separate makes the core
# application logic clearer and easier to test.

def fetch_from_newsapi(query: str, api_key: str, page_size: int = 20) -> List[Dict]:
    """Fetch news articles matching a query using the NewsAPI.

    Parameters
    ----------
    query : str
        The search string containing keywords, phrases or company names.
    api_key : str
        Your NewsAPI API key.  Obtain a key at https://newsapi.org and store
        it securely via Streamlit secrets or an environment variable.
    page_size : int, optional
        Maximum number of articles to retrieve (default is 20).

    Returns
    -------
    List[Dict]
        A list of article dictionaries returned by the API.
    """
    endpoint = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": api_key,
    }
    try:
        response = requests.get(endpoint, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        st.error(f"Failed to fetch articles from NewsAPI: {e}")
        return []

    return data.get("articles", [])


def fetch_from_google_rss(query: str, limit: int = 20) -> List[Dict]:
    """Fetch news items using the Google News RSS feed.

    Google publishes RSS feeds for arbitrary search queries.  You can
    retrieve up to a specified number of entries per keyword.  See
    https://news.google.com/rss/search?q=<SEARCH_QUERY> for details
    about how the RSS feed works【739508586957365†L26-L40】.

    Parameters
    ----------
    query : str
        Search string for the RSS feed.  Spaces are URL‑encoded.
    limit : int, optional
        Maximum number of entries to return per feed (default is 20).

    Returns
    -------
    List[Dict]
        A list of dictionaries with similar keys to NewsAPI results.
    """
    encoded = urllib.parse.quote(query)
    feed_url = f"https://news.google.com/rss/search?q={encoded}"
    feed = feedparser.parse(feed_url)
    entries = feed.entries[:limit]
    articles: List[Dict] = []
    for entry in entries:
        # Attempt to extract a publication date.  RSS feeds provide pubDate
        # strings which we parse to datetime; if parsing fails we leave it as
        # None and assign a default recency score later.
        published_at = None
        if "published" in entry:
            try:
                published_at = datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc)
            except Exception:
                published_at = None
        articles.append(
            {
                "title": entry.get("title", ""),
                "description": entry.get("summary", ""),
                "url": entry.get("link", ""),
                "source": {"name": entry.get("source", {}).get("title", "Google News")},
                "publishedAt": published_at.isoformat() if published_at else None,
            }
        )
    return articles


def scrape_article(url: str) -> Tuple[str, datetime.datetime]:
    """Attempt to download and parse a news article.

    The ``newspaper3k`` library extracts the full text and publication date
    of articles.  Some sites block scrapers or use complex layouts; if
    extraction fails this function returns an empty string and ``None``.

    Parameters
    ----------
    url : str
        URL of the news article to scrape.

    Returns
    -------
    Tuple[str, datetime.datetime]
        A tuple of the article text and its publish date (if available).
    """
    article = Article(url)
    try:
        article.download()
        article.parse()
        text = article.text
        date = article.publish_date
        return text, date
    except Exception:
        return "", None


def recency_score(published_at: str) -> float:
    """Calculate a recency score between 0 and 1 based on publication date.

    Recent articles receive scores closer to 1, while older articles are
    penalised.  Articles older than seven days receive a score of 0.

    Parameters
    ----------
    published_at : str
        ISO‑formatted timestamp (e.g., ``2025-07-29T12:00:00Z``).  May be
        ``None`` if unknown.

    Returns
    -------
    float
        A value in the range [0, 1].
    """
    if not published_at:
        return 0.0
    try:
        dt = datetime.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except Exception:
        return 0.0
    now = datetime.datetime.now(datetime.timezone.utc)
    delta_days = (now - dt).total_seconds() / 86400.0
    return max(0.0, 1.0 - min(delta_days, 7) / 7.0)


def authority_score(source_name: str) -> float:
    """Assign a heuristic authority score to a news source.

    The list below contains widely recognised news organisations.  See the
    News Literacy Project's five steps for vetting a news source【559532761496453†L84-L109】,
    which highlight the importance of standards, transparency and accountability
    in credible journalism.  If the source is not in the list, a default
    modest score is returned.

    Parameters
    ----------
    source_name : str
        The name of the news outlet as provided by the API or RSS feed.

    Returns
    -------
    float
        An authority score in the range [0, 1], higher means more authoritative.
    """
    # Normalise name for comparison
    name = (source_name or "").lower()
    authoritative_outlets = {
        "associated press": 1.0,
        "ap news": 1.0,
        "reuters": 1.0,
        "bbc news": 1.0,
        "the new york times": 0.9,
        "the wall street journal": 0.9,
        "the washington post": 0.9,
        "financial times": 0.9,
        "the guardian": 0.8,
        "al jazeera": 0.8,
        "npr": 0.8,
        "cnn": 0.7,
        "cnbc": 0.7,
        "bloomberg": 0.8,
    }
    for key, score in authoritative_outlets.items():
        if key in name:
            return score
    return 0.3  # default modest authority for unknown sources


def prioritise_articles(articles: List[Dict]) -> List[Dict]:
    """Compute priority scores for a list of article dictionaries.

    The priority score is a weighted combination of recency (70 %) and
    authority (30 %).  Scores are added to the article dictionaries under
    the key ``priority``.  Articles are then sorted in descending order.

    Parameters
    ----------
    articles : list
        A list of articles returned by either NewsAPI or Google RSS.

    Returns
    -------
    list
        The list of articles annotated with a ``priority`` field and sorted
        from highest to lowest.
    """
    for art in articles:
        rec = recency_score(art.get("publishedAt"))
        auth = authority_score(art.get("source", {}).get("name"))
        # Weighted combination; adjust as needed
        art["recency"] = rec
        art["authority"] = auth
        art["priority"] = 0.7 * rec + 0.3 * auth
    return sorted(articles, key=lambda x: x["priority"], reverse=True)


# -----------------------------------------------------------------------------
# Streamlit application
#
def main() -> None:
    """Entrypoint for the Streamlit media monitoring dashboard."""
    # Download the NLTK tokenizer data required by newspaper3k if not already
    # present.  The Punkt tokenizer is used internally by newspaper3k to split
    # text into sentences.
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt", quiet=True)

    st.set_page_config(page_title="Media Monitoring System", layout="wide")
    st.title("Media Monitoring System – Meltwater Clone")

    # Sidebar inputs
    st.sidebar.header("Search Settings")
    keyword_input = st.sidebar.text_input(
        "Enter keywords or company names (comma separated)",
        value="AI startups, Fintech, mergers and acquisitions"
    )
    max_articles = st.sidebar.slider(
        "Maximum articles per keyword",
        min_value=5,
        max_value=50,
        value=20
    )
    if st.sidebar.button("Search"):
        run_monitoring(keyword_input, max_articles)

    # Automatically run once on page load for demonstration
    if "initial_run" not in st.session_state:
        st.session_state.initial_run = True
        run_monitoring(keyword_input, max_articles)


def run_monitoring(query_string: str, max_articles: int) -> None:
    """Run the monitoring process for a given set of queries.

    This function performs the actual retrieval, scraping and prioritisation of
    articles.  It writes results into the Streamlit app, including a table of
    articles and the full text for each selected article.

    Parameters
    ----------
    query_string : str
        Comma‑separated keywords or company names.
    max_articles : int
        Maximum number of articles to retrieve per keyword.
    """
    with st.spinner("Fetching news articles…"):
        queries = [q.strip() for q in query_string.split(",") if q.strip()]
        api_key = None
        # Try to read API key from Streamlit secrets or environment
        if hasattr(st, "secrets") and "NEWS_API_KEY" in st.secrets:
            api_key = st.secrets["NEWS_API_KEY"]
        elif os.getenv("NEWS_API_KEY"):
            api_key = os.getenv("NEWS_API_KEY")
        else:
            st.info(
                "No NEWS_API_KEY found.  The app will use the public Google News RSS feed instead, which may return limited and delayed results.\n"
                "To receive more comprehensive coverage, create a free account on NewsAPI.org and add your key to the Streamlit secrets as 'NEWS_API_KEY'."
            )

        all_articles: List[Dict] = []
        for q in queries:
            if api_key:
                articles = fetch_from_newsapi(q, api_key, page_size=max_articles)
            else:
                articles = fetch_from_google_rss(q, limit=max_articles)
            all_articles.extend(articles)

        if not all_articles:
            st.warning("No articles were found for the specified queries.")
            return

        # Optionally scrape the full content and update publishedAt if missing
        scraped_results = []
        for art in all_articles:
            url = art.get("url")
            # Only scrape if no description or to enrich the article; avoid being blocked
            text, pub_date = scrape_article(url) if url else ("", None)
            if not art.get("publishedAt") and pub_date:
                art["publishedAt"] = pub_date.isoformat()
            art["content"] = text
            scraped_results.append(art)

        prioritised = prioritise_articles(scraped_results)

        # Display results
        df = pd.DataFrame([
            {
                "Priority Score": round(a["priority"], 3),
                "Recency": round(a["recency"], 3),
                "Authority": round(a["authority"], 3),
                "Date": a.get("publishedAt"),
                "Source": a.get("source", {}).get("name"),
                "Title": a.get("title"),
                "URL": a.get("url"),
            }
            for a in prioritised
        ])
        st.subheader("Results")
        st.markdown("**Articles are prioritised by recency and source authority.** Use the column headers to sort.")
        st.dataframe(df, use_container_width=True)

        # Show details of top article or selected row
        st.subheader("Article Details")
        selected_index = st.number_input(
            "Select an article to view details (0 = first article)",
            min_value=0,
            max_value=len(prioritised) - 1,
            value=0,
            step=1,
            format="%i"
        )
        selected = prioritised[int(selected_index)]
        st.markdown(f"### {selected.get('title')}")
        st.markdown(f"**Source:** {selected.get('source', {}).get('name')}  ")
        st.markdown(f"**Published:** {selected.get('publishedAt')}  ")
        st.markdown(f"**URL:** [{selected.get('url')}]({selected.get('url')})")
        if selected.get("content"):
            st.markdown("#### Full Text")
            st.write(selected["content"])
        else:
            st.info("Full text could not be extracted from this article.\n"
                    "Try clicking the URL above to read the article at the source.")


if __name__ == "__main__":
    main()