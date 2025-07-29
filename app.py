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
from goose3 import Goose  # fallback article extractor (Apache-2.0 licensed)
from readability import Document  # final fallback article extractor (Apache‑licensed)
from bs4 import BeautifulSoup  # used to convert readability HTML into plain text
import feedparser
import nltk

# Mapping of common publication names to their primary domain names.  This
# dictionary makes it easy to restrict searches to specific outlets when
# users provide publication names instead of raw domain strings.  Each key
# corresponds to a lower‑cased publication name, and the value is a list
# of domains associated with that publication.  For example, "the times"
# maps to ``thetimes.co.uk``, while "mining journal" includes both
# ``mining-journal.com`` and ``miningjournal.com`` because the brand
# operates across multiple domains.  Feel free to extend this mapping as
# needed for additional publications.
PUBLICATION_DOMAINS: Dict[str, List[str]] = {
    "the times": ["thetimes.co.uk"],
    "the telegraph": ["telegraph.co.uk"],
    "daily mail": ["dailymail.co.uk"],
    "mining review africa": ["miningreview.com"],
    "mining weekly": ["miningweekly.com"],
    "mining journal": ["mining-journal.com", "miningjournal.com"],
    "mining magazine": ["miningmagazine.com"],
    "mining.com": ["mining.com"],
    "energy voice": ["energyvoice.com"],
    "upstreamonline.com": ["upstreamonline.com"],
    "financial times": ["ft.com"],
    "reuters": ["reuters.com"],
    "bloomberg": ["bloomberg.com"],
}

# -----------------------------------------------------------------------------
# Utility functions
#
# The following helper functions encapsulate the functionality used throughout
# the application: fetching news articles, scraping content and calculating
# prioritisation scores.  Keeping these functions separate makes the core
# application logic clearer and easier to test.

def fetch_from_newsapi(query: str, api_key: str, page_size: int = 20, domains: str | None = None) -> List[Dict]:
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
    # If domains have been specified, restrict the search.  The NewsAPI
    # documentation notes that the ``domains`` parameter accepts a
    # comma‑separated list of domains (e.g. "reuters.com, bloomberg.com").  If
    # present, we simply add it to the query parameters.  Note that not all
    # publications are supported by NewsAPI.
    if domains:
        params["domains"] = domains
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


def fetch_from_google_site_search(query: str, domain: str, days: int = 7, limit: int = 20) -> List[Dict]:
    """Fetch news items from a specific website using Google News RSS.

    Google News RSS supports advanced search operators such as `site:` and
    `when:` to limit results to a particular domain and recency.  For
    example, the search `site:reuters.com when:1h` returns Reuters stories
    published in the last hour【168391965472992†L183-L221】.  Replacing the `/search` path
    with `/rss/search` yields an RSS feed for the same query【168391965472992†L211-L223】.
    This helper function constructs such a query by combining a keyword
    with a site filter and recency window, then delegates to
    ``fetch_from_google_rss`` for parsing.

    Parameters
    ----------
    query : str
        Search keywords (e.g., "AI startups").  May be an empty string to
        fetch recent articles from the domain irrespective of keywords.
    domain : str
        The domain to restrict results to (e.g., "reuters.com").
    days : int, optional
        Limit results to articles published within the last ``days`` days
        using the `when:` operator (default is 7).
    limit : int, optional
        Maximum number of entries to return (default is 20).

    Returns
    -------
    List[Dict]
        A list of article dictionaries similar to ``fetch_from_google_rss``.
    """
    # Build the search string.  The `site:` operator restricts results to
    # the given domain, and the `when:` operator restricts the time window
    # (e.g., 7d for the last seven days)【168391965472992†L183-L221】.
    parts = []
    if query:
        parts.append(query.strip())
    if domain:
        parts.append(f"site:{domain.strip()}")
    if days:
        parts.append(f"when:{days}d")
    search_str = " ".join(parts)
    return fetch_from_google_rss(search_str, limit=limit)


def scrape_article(url: str) -> Tuple[str, datetime.datetime]:
    """Attempt to download and parse a news article using multiple extractors.

    This function first tries ``newspaper3k`` to obtain the full article text and
    its publish date.  ``newspaper3k`` relies on lxml's HTML cleaner and works
    well on many mainstream sites, but some sites block scrapers or have
    unusual layouts.  If ``newspaper3k`` fails to extract any text, the
    function falls back to the ``goose3`` extractor, which is licensed under
    Apache 2.0 and can extract the main body, meta data and images from
    arbitrary articles【275271027204652†L203-L371】.  If both extractors fail, an empty
    string and ``None`` are returned.

    Parameters
    ----------
    url : str
        URL of the news article to scrape.

    Returns
    -------
    Tuple[str, datetime.datetime]
        A tuple of the article text and its publish date (if available).
    """
    """Attempt to download and parse a news article using multiple extractors.

    This function first tries ``newspaper3k`` to obtain the full article text and
    its publish date.  ``newspaper3k`` relies on lxml's HTML cleaner and works
    well on many mainstream sites, but some sites block scrapers or have
    unusual layouts.  If ``newspaper3k`` fails to extract any text, the
    function falls back to the ``goose3`` extractor, which is licensed under
    Apache 2.0 and can extract the main body, meta data and images from
    arbitrary articles【275271027204652†L203-L371】.  Finally, if both extractors fail,
    the function uses ``readability‑lxml`` to extract the main content from
    raw HTML【842996678366491†L94-L126】.  When all extractors fail, an empty
    string and ``None`` are returned.

    Parameters
    ----------
    url : str
        URL of the news article to scrape.

    Returns
    -------
    Tuple[str, datetime.datetime]
        A tuple of the article text and its publish date (if available).
    """
    # Try newspaper3k first
    try:
        article = Article(url)
        article.download()
        article.parse()
        text = article.text
        date = article.publish_date
        if text:
            return text, date
    except Exception:
        pass
    # Fallback to Goose3
    try:
        g = Goose({"browser_user_agent": "Mozilla/5.0"})
        content = g.extract(url=url)
        text = getattr(content, "cleaned_text", "") or ""
        date = getattr(content, "publish_date", None)
        if text:
            return text, date
    except Exception:
        pass
    # Final fallback to readability-lxml
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        doc = Document(resp.text)
        # ``summary()`` returns HTML containing the main content【842996678366491†L94-L126】
        html_content = doc.summary()  # type: ignore[attr-defined]
        soup = BeautifulSoup(html_content, "html.parser")
        # Extract plain text from the HTML
        text = soup.get_text(separator="\n").strip()
        # readability-lxml does not provide a publish date; return None
        return text, None
    except Exception:
        return "", None


def fetch_from_gdelt(query: str, max_records: int = 20) -> List[Dict]:
    """Fetch articles from the GDELT DOC 2.0 API.

    The GDELT Project monitors news coverage across the world and machine
    translates it into English.  Its DOC 2.0 API allows searching over a
    rolling three‑month window and supports JSON output【317432739810327†L21-L63】.  This
    function queries the API in ``ArtList`` mode and returns a list of
    dictionaries similar to the NewsAPI format.  If the API call fails or
    returns an unexpected schema, an empty list is returned.

    Parameters
    ----------
    query : str
        Search string for the API.
    max_records : int, optional
        Maximum number of articles to retrieve (default is 20).

    Returns
    -------
    List[Dict]
        A list of article dictionaries with keys: ``title``, ``description``,
        ``url``, ``source`` and ``publishedAt``.
    """
    base_url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": query,
        "mode": "ArtList",  # return a list of matching articles
        "maxrecords": max_records,
        "format": "json",  # JSONFeed 1.0 format
        "sort": "datedesc",  # newest first
        "timespan": "1 week",  # restrict to last 7 days
    }
    try:
        resp = requests.get(base_url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    # The JSONFeed format returns an ``items`` list
    articles_list = []
    items = data.get("items") or data.get("articles") or []
    for item in items:
        title = item.get("title", "")
        url = item.get("url", item.get("id", ""))
        # published date may be in ISO 8601 format or absent
        date_str = item.get("date_published") or item.get("publishedAt")
        if date_str:
            try:
                dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                published_at = dt.isoformat()
            except Exception:
                published_at = None
        else:
            published_at = None
        articles_list.append(
            {
                "title": title,
                "description": item.get("summary", ""),
                "url": url,
                "source": {"name": item.get("source", {}).get("title", "GDELT")},
                "publishedAt": published_at,
            }
        )
    return articles_list


def fetch_from_guardian(query: str, api_key: str, page_size: int = 20) -> List[Dict]:
    """Fetch articles from The Guardian Open Platform.

    The Guardian provides an [Open Platform](https://open-platform.theguardian.com)
    that exposes the full archive of articles dating back to 1999.  Developers
    can register for a free key for non‑commercial usage, which allows up to
    500 calls per day and includes access to the article body text【666270658916805†L21-L35】.
    To retrieve the full body text, the API supports a `show-fields` filter
    parameter.  Setting `show-fields=body` returns the body of each article
    【555774334167872†L49-L53】, so there is no need for additional scraping.

    Parameters
    ----------
    query : str
        Search string for the API.
    api_key : str
        Developer or commercial API key for the Guardian content API.
    page_size : int, optional
        Number of results to return (default is 20).

    Returns
    -------
    List[Dict]
        A list of article dictionaries with keys: ``title``, ``description``
        (lead paragraph), ``url``, ``source`` and ``publishedAt``.  The
        ``content`` field contains the plain text body extracted from the API.
    """
    endpoint = "https://content.guardianapis.com/search"
    params = {
        "q": query,
        "api-key": api_key,
        "page-size": page_size,
        "order-by": "newest",
        # Request the body field to get full article text【555774334167872†L49-L53】
        "show-fields": "body,trailText",
    }
    try:
        resp = requests.get(endpoint, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        # Do not display user secrets in the error; log generic message
        st.error(f"Failed to fetch articles from The Guardian API: {e}")
        return []
    results = data.get("response", {}).get("results", [])
    articles: List[Dict] = []
    for item in results:
        title = item.get("webTitle", "")
        url = item.get("webUrl", "")
        published_at = item.get("webPublicationDate")
        # `trailText` is a short summary; `body` contains HTML of the full article
        fields = item.get("fields", {}) or {}
        html_body = fields.get("body", "")
        # Convert the HTML body to plain text
        text = BeautifulSoup(html_body, "html.parser").get_text(separator="\n").strip() if html_body else ""
        description = fields.get("trailText", "")
        articles.append(
            {
                "title": title,
                "description": description,
                "url": url,
                "source": {"name": "The Guardian"},
                "publishedAt": published_at,
                "content": text,
            }
        )
    return articles


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
        "Maximum articles per keyword or site",
        min_value=5,
        max_value=50,
        value=20
    )
    # Allow users to specify either raw domains (e.g. reuters.com) or
    # human‑readable publication names (e.g. The Times, Daily Mail).  If
    # names are supplied, they will be looked up in the ``PUBLICATION_DOMAINS``
    # mapping to derive the corresponding domain(s).  You can combine
    # publication names and domains in the same comma‑separated string.
    domains_input = st.sidebar.text_input(
        "Restrict to specific domains or publications (comma separated, optional)",
        value=""
    )
    if st.sidebar.button("Search"):
        run_monitoring(keyword_input, max_articles, domains_input)

    # Automatically run once on page load for demonstration
    if "initial_run" not in st.session_state:
        st.session_state.initial_run = True
        run_monitoring(keyword_input, max_articles, domains_input)


def run_monitoring(query_string: str, max_articles: int, domains_input: str = "") -> None:
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
        # Load API keys from Streamlit secrets or environment variables
        news_api_key: str | None = None
        guardian_key: str | None = None
        if hasattr(st, "secrets"):
            news_api_key = st.secrets.get("NEWS_API_KEY")
            guardian_key = st.secrets.get("GUARDIAN_API_KEY")
        # Fallback to environment variables if secrets not configured
        news_api_key = news_api_key or os.getenv("NEWS_API_KEY")
        guardian_key = guardian_key or os.getenv("GUARDIAN_API_KEY")

        if not news_api_key:
            st.info(
                "No NEWS_API_KEY found.  The app will use the public Google News RSS feed instead, which may return limited and delayed results.\n"
                "To receive more comprehensive coverage, create a free account on NewsAPI.org and add your key to the Streamlit secrets as 'NEWS_API_KEY'."
            )
        if not guardian_key:
            st.info(
                "No GUARDIAN_API_KEY provided.  To include The Guardian's archive and full article texts in search results, register for a free developer key on The Guardian Open Platform and add it as 'GUARDIAN_API_KEY' in your secrets."
            )

        all_articles: List[Dict] = []
        # Parse any domain restrictions or publication names from the argument.
        # For each comma‑separated token, check if it matches a key in
        # ``PUBLICATION_DOMAINS``.  If so, extend the domain list with all
        # associated domains; otherwise assume the token itself is a domain.
        domain_list: List[str] = []
        for token in [d.strip() for d in domains_input.split(",") if d.strip()]:
            key = token.lower()
            if key in PUBLICATION_DOMAINS:
                domain_list.extend(PUBLICATION_DOMAINS[key])
            else:
                # Accept bare domains like "reuters.com" or names not in mapping
                domain_list.append(token)
        # Remove duplicates while preserving order
        seen: set[str] = set()
        domain_list = [d for d in domain_list if not (d in seen or seen.add(d))]
        for q in queries:
            # Prefer NewsAPI when a key is available; otherwise fall back to RSS
            if news_api_key:
                # If a domain list is provided, join into a comma‑separated string
                # for the NewsAPI "domains" parameter.  Otherwise pass None.
                dom_param = ",".join(domain_list) if domain_list else None
                articles = fetch_from_newsapi(q, news_api_key, page_size=max_articles, domains=dom_param)
            else:
                articles = fetch_from_google_rss(q, limit=max_articles)
            all_articles.extend(articles)
            # If domains have been specified, query Google News RSS for each domain with site restriction
            for domain in domain_list:
                site_articles = fetch_from_google_site_search(q, domain, days=7, limit=max_articles)
                all_articles.extend(site_articles)
            # Query the Guardian API if a key is available
            if guardian_key:
                guardian_articles = fetch_from_guardian(q, guardian_key, page_size=max_articles)
                all_articles.extend(guardian_articles)
            # Also query the GDELT DOC 2.0 API for broader coverage
            gdelt_articles = fetch_from_gdelt(q, max_records=max_articles)
            all_articles.extend(gdelt_articles)

        if not all_articles:
            st.warning("No articles were found for the specified queries.")
            return

        # Optionally scrape the full content and update publishedAt if missing
        scraped_results = []
        for art in all_articles:
            url = art.get("url")
            # Use existing content if provided by API (e.g., Guardian); otherwise scrape
            if art.get("content"):
                text = art["content"]
                pub_date = None
            else:
                text, pub_date = scrape_article(url) if url else ("", None)
            # If the article had no publication date from the API but scraping succeeded, update it
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