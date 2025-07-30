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
from typing import Dict, List, Tuple, Optional

import pandas as pd
import requests
import streamlit as st
from newspaper import Article

# Optional extractors: Goose3 and readability‑lxml provide additional scraping
# resilience but may not always be installed.  We import them lazily in
# ``scrape_article()`` so that the absence of these packages does not crash
# the application at startup.  If they are unavailable, the function simply
# skips their usage.
try:
    from goose3 import Goose  # type: ignore[import-not-found]
except ImportError:
    Goose = None  # type: ignore[assignment]

try:
    from readability import Document  # type: ignore[import-not-found]
    from bs4 import BeautifulSoup  # type: ignore[import-not-found]
except ImportError:
    Document = None  # type: ignore[assignment]
    BeautifulSoup = None  # type: ignore[assignment]
import feedparser
import nltk

# Optional sentiment analysis: VADER is a lexicon‑ and rule‑based sentiment
# analyser specifically attuned to sentiments expressed in social media and
# performs well on other domains as well【528669426112280†L32-L35】.  If the
# package is unavailable, the application will skip sentiment scoring.
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore[import-not-found]
except ImportError:
    SentimentIntensityAnalyzer = None  # type: ignore[assignment]

# Report generation dependencies.  We use ReportLab to build PDF reports
# styled after the provided Word template.  The PIL library is used via
# ReportLab's ImageReader; both packages are optional at runtime but
# declared in requirements.  If unavailable, report generation will fail
# gracefully.
try:
    from reportlab.lib.pagesizes import A4  # type: ignore[import-not-found]
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        Image as RLImage,
        PageBreak,
    )
    from reportlab.lib import colors  # type: ignore[import-not-found]
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # type: ignore[import-not-found]
    from reportlab.lib.units import inch  # type: ignore[import-not-found]
    from reportlab.lib.utils import ImageReader  # type: ignore[import-not-found]
except ImportError:
    # If ReportLab is missing, we will not be able to generate PDFs
    A4 = None  # type: ignore[assignment]
    SimpleDocTemplate = None  # type: ignore[assignment]
    Paragraph = None  # type: ignore[assignment]
    Spacer = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    TableStyle = None  # type: ignore[assignment]
    RLImage = None  # type: ignore[assignment]
    PageBreak = None  # type: ignore[assignment]
    colors = None  # type: ignore[assignment]
    getSampleStyleSheet = None  # type: ignore[assignment]
    ParagraphStyle = None  # type: ignore[assignment]
    inch = None  # type: ignore[assignment]
    ImageReader = None  # type: ignore[assignment]

import io
from pathlib import Path

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


# -----------------------------------------------------------------------------
# Sentiment analysis and tier classification
#
# To provide richer insights, the application assigns a simple sentiment
# classification to each article and groups publications into broad tiers.  The
# sentiment is computed using VADER, a lexicon‑ and rule‑based model that
# returns a compound score between ‑1 (very negative) and 1 (very positive)
#【126899030742881†L284-L304】.  We convert the compound score into three labels: positive,
# neutral or negative, following the conventional thresholds described in
# the VADER documentation【126899030742881†L372-L393】.  If the VADER package is not
# installed, sentiment is left undefined and the report will omit that
# column.

# Create a global analyser instance if the dependency is available.  Creating
# this object once avoids repeatedly downloading the VADER lexicon.
if SentimentIntensityAnalyzer is not None:
    _vader_analyser: Optional[SentimentIntensityAnalyzer] = SentimentIntensityAnalyzer()
else:
    _vader_analyser = None


def compute_sentiment(text: str) -> Tuple[Optional[str], float]:
    """Compute a sentiment label and compound score for a piece of text.

    Parameters
    ----------
    text : str
        The article body or description from which to derive sentiment.

    Returns
    -------
    tuple
        A tuple ``(label, score)`` where ``label`` is one of ``"positive"``,
        ``"neutral"``, ``"negative"`` or ``None`` if sentiment cannot be
        calculated, and ``score`` is the compound VADER score in the range
        [‑1, 1].  A ``None`` label indicates that VADER is not installed.
    """
    if not text or _vader_analyser is None:
        return None, 0.0
    try:
        scores = _vader_analyser.polarity_scores(text)
        compound = scores.get("compound", 0.0)
        if compound >= 0.05:
            label = "positive"
        elif compound <= -0.05:
            label = "negative"
        else:
            label = "neutral"
        return label, compound
    except Exception:
        return None, 0.0


# Define publication tiers.  Major international outlets with strong editorial
# standards are classified as ``Top``; national or regional papers fall under
# ``Mid``; industry‑specific titles form the ``Trade`` tier.  These lists are
# heuristic and can be expanded via configuration or by editing the code.
TOP_TIER_OUTLETS = {
    "reuters",
    "financial times",
    "bloomberg",
    "the new york times",
    "the wall street journal",
    "bbc news",
}
MID_TIER_OUTLETS = {
    "the times",
    "the telegraph",
    "daily mail",
    "the guardian",
    "the independent",
}
TRADE_TIER_OUTLETS = {
    "mining review africa",
    "mining weekly",
    "mining journal",
    "mining magazine",
    "mining.com",
    "energy voice",
    "upstreamonline.com",
}


def assign_tier(source_name: str) -> Optional[str]:
    """Assign a publication to a tier based on its name.

    Parameters
    ----------
    source_name : str
        The name of the news outlet as returned by RSS or API.

    Returns
    -------
    str or None
        ``"Top"``, ``"Mid"``, ``"Trade"`` for recognised outlets or ``None``
        if the source is unclassified.  Blogs and unknown sites return
        ``None`` and are excluded from PDF reports.
    """
    if not source_name:
        return None
    name = source_name.lower()
    # Check trade first because some names may overlap with generic terms
    for outlet in TRADE_TIER_OUTLETS:
        if outlet in name:
            return "Trade"
    for outlet in MID_TIER_OUTLETS:
        if outlet in name:
            return "Mid"
    for outlet in TOP_TIER_OUTLETS:
        if outlet in name:
            return "Top"
    return None


def generate_pdf_report(articles: List[Dict], include_sentiment: bool) -> Optional[bytes]:
    """Generate a PDF report from selected articles.

    The report replicates the layout of the provided Word template.  It
    features a header image with a grey bar labelled "Press Coverage", a
    date and logo row, grouped tables for each publication tier and a
    footer with contact details and icons.  If ReportLab is not
    available, this function returns ``None``.

    Parameters
    ----------
    articles : list of dict
        The selected articles to include in the report.  Each dictionary
        should contain ``title``, ``source`` (with ``name``), ``publishedAt``,
        ``url``, ``tier`` and optionally ``sentiment``.
    include_sentiment : bool
        If True, append a sentiment column to each table.

    Returns
    -------
    bytes or None
        The PDF file as bytes if successful; otherwise ``None``.
    """
    if A4 is None or SimpleDocTemplate is None:
        # ReportLab is not installed
        return None
    # Sort articles by tier according to the desired order
    tier_order = ["Top", "Mid", "Trade"]
    grouped: Dict[str, List[Dict]] = {t: [] for t in tier_order}
    for art in articles:
        tier = art.get("tier")
        if tier in grouped:
            grouped[tier].append(art)
    # Create a buffer to hold the PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    # Custom styles for headings and table text
    heading_style = ParagraphStyle(
        name="Heading",
        parent=styles["Heading2"],
        fontSize=14,
        leading=16,
        spaceAfter=6,
    )
    table_text_style = ParagraphStyle(
        name="TableText",
        parent=styles["BodyText"],
        fontSize=10,
        leading=12,
    )
    table_link_style = ParagraphStyle(
        name="TableLink",
        parent=styles["BodyText"],
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#0066CC"),
        underline=True,
    )
    elements: List = []
    # For each tier, build a table if there are articles
    for tier in tier_order:
        items = grouped.get(tier) or []
        if not items:
            continue
        # Section heading
        elements.append(Paragraph(f"{tier} Tier", heading_style))
        # Table header
        header = ["Headline", "Publication", "Date", "URL"]
        if include_sentiment:
            header.append("Sentiment")
        data = [header]
        # Populate rows
        for art in items:
            title = art.get("title") or "Untitled"
            pub_name = art.get("source", {}).get("name", "")
            date_str = art.get("publishedAt") or ""
            # Use a hyperlink for the URL column; ReportLab's Paragraph supports
            # simple markup: <a href="...">text</a>
            url = art.get("url", "")
            link_para = Paragraph(f"<a href='{url}'>Link</a>", table_link_style)
            row = [
                Paragraph(title, table_text_style),
                Paragraph(pub_name, table_text_style),
                Paragraph(date_str.split("T")[0] if date_str else "", table_text_style),
                link_para,
            ]
            if include_sentiment:
                sentiment_label = art.get("sentiment") or ""
                row.append(Paragraph(sentiment_label.capitalize(), table_text_style))
            data.append(row)
        # Determine column widths; adjust for sentiment column
        if include_sentiment:
            col_widths = [3.5 * inch, 1.5 * inch, 1.0 * inch, 1.2 * inch, 1.0 * inch]
        else:
            col_widths = [4.0 * inch, 1.7 * inch, 1.2 * inch, 1.6 * inch]
        table = Table(data, colWidths=col_widths, repeatRows=1)
        # Style the table: grey header, alternating row shading, grid lines
        style_commands = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DDDDDD')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#333333')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#CCCCCC')),
        ]
        table.setStyle(TableStyle(style_commands))
        elements.append(table)
        elements.append(Spacer(1, 0.3 * inch))
    # Function to draw header and footer on each page
    def _header_footer(canvas, doc):
        width, height = A4
        # Header image
        header_path = Path(__file__).parent / 'assets' / 'header.jpg'
        logo_path = Path(__file__).parent / 'assets' / 'br_logo.png'
        icon_globe = Path(__file__).parent / 'assets' / 'icon_globe.png'
        icon_twitter = Path(__file__).parent / 'assets' / 'icon_twitter.png'
        icon_linkedin = Path(__file__).parent / 'assets' / 'icon_linkedin.png'
        icon_email = Path(__file__).parent / 'assets' / 'icon_email.png'
        icon_phone = Path(__file__).parent / 'assets' / 'icon_phone.png'
        # Header height (in points)
        header_height = 2.0 * inch
        bar_height = 0.35 * inch
        y_top = height - doc.topMargin
        # Draw the header image stretched to page width
        try:
            canvas.drawImage(
                str(header_path),
                0,
                y_top - header_height,
                width=width,
                height=header_height,
                preserveAspectRatio=True,
                mask='auto'
            )
        except Exception:
            # If the image cannot be drawn, silently skip
            pass
        # Overlay grey bar for the title
        canvas.setFillColor(colors.HexColor('#485C6E'))
        canvas.rect(0, y_top - header_height - bar_height, width, bar_height, stroke=0, fill=1)
        # Title text
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', 16)
        title_text = 'Press Coverage'
        text_width = canvas.stringWidth(title_text, 'Helvetica-Bold', 16)
        canvas.drawString(width - doc.rightMargin - text_width, y_top - header_height - bar_height + 0.1 * inch, title_text)
        # Date text
        date_str = datetime.datetime.now().strftime('%A %d %B %Y')
        canvas.setFont('Helvetica', 12)
        canvas.drawString(doc.leftMargin, y_top - header_height - bar_height - 0.2 * inch, date_str)
        # Logo (draw to the right of the date)
        try:
            canvas.drawImage(
                str(logo_path),
                width - doc.rightMargin - 1.0 * inch,
                y_top - header_height - bar_height - 0.5 * inch,
                width=0.8 * inch,
                height=0.8 * inch,
                mask='auto'
            )
        except Exception:
            pass
        # Footer: grey divider line
        canvas.setFillColor(colors.HexColor('#E5E5E5'))
        canvas.rect(0, doc.bottomMargin - 0.4 * inch, width, 0.02 * inch, stroke=0, fill=1)
        # Footer icons and text
        # Starting position
        x_start = doc.leftMargin
        y_footer = doc.bottomMargin - 0.35 * inch
        icon_size = 0.15 * inch
        gap = 0.05 * inch
        icons = [icon_globe, icon_twitter, icon_linkedin, icon_email, icon_phone]
        for icon in icons:
            try:
                canvas.drawImage(
                    str(icon),
                    x_start,
                    y_footer,
                    width=icon_size,
                    height=icon_size,
                    mask='auto'
                )
            except Exception:
                pass
            x_start += icon_size + gap
        # Footer text (address)
        footer_text = 'BR, 4-5 Castle Court, London EC3V 9DL'
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#606060'))
        canvas.drawRightString(width - doc.rightMargin, y_footer + 0.02 * inch, footer_text)
    # Build the document
    doc.build(elements, onFirstPage=_header_footer, onLaterPages=_header_footer)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def fetch_from_google_rss(query: str, limit: int = 20, *, hl: str | None = None, gl: str | None = None, ceid: str | None = None) -> List[Dict]:
    """Fetch news items using the Google News RSS feed.

    Google publishes RSS feeds for arbitrary search queries.  This helper
    supports optional regional parameters to restrict results to a specific
    country or language.  The `hl` parameter controls the UI language (e.g.
    ``en-GB``), `gl` sets the geolocation (e.g. ``GB``), and `ceid`
    combines country and language (e.g. ``GB:en``).  These parameters are
    optional and only added to the feed URL when provided.  See
    https://news.google.com/rss/search?q=<SEARCH_QUERY> for details about how
    the RSS feed works【739508586957365†L26-L40】.

    Parameters
    ----------
    query : str
        Search string for the RSS feed.  Spaces are URL‑encoded.
    limit : int, optional
        Maximum number of entries to return per feed (default is 20).
    hl : str, optional
        UI language code (e.g., ``en-GB``).  Only used when provided.
    gl : str, optional
        Geolocation country code (e.g., ``GB``).  Only used when provided.
    ceid : str, optional
        Combined country and language (e.g., ``GB:en``).  Only used when provided.

    Returns
    -------
    List[Dict]
        A list of dictionaries with similar keys to NewsAPI results.
    """
    encoded = urllib.parse.quote(query)
    # Start with the base search URL
    feed_url = f"https://news.google.com/rss/search?q={encoded}"
    # Append optional regional parameters if provided
    params = []
    if hl:
        params.append(f"hl={urllib.parse.quote(hl)}")
    if gl:
        params.append(f"gl={urllib.parse.quote(gl)}")
    if ceid:
        params.append(f"ceid={urllib.parse.quote(ceid)}")
    if params:
        feed_url = f"{feed_url}&{'&'.join(params)}"
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


def fetch_from_google_site_search(
    query: str,
    domain: str,
    days: int = 7,
    limit: int = 20,
    *,
    hl: str | None = None,
    gl: str | None = None,
    ceid: str | None = None,
) -> List[Dict]:
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
    parts: List[str] = []
    if query:
        parts.append(query.strip())
    if domain:
        parts.append(f"site:{domain.strip()}")
    if days:
        parts.append(f"when:{days}d")
    search_str = " ".join(parts)
    # Delegate to the RSS fetcher, forwarding any regional parameters
    return fetch_from_google_rss(search_str, limit=limit, hl=hl, gl=gl, ceid=ceid)


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
    # Fallback to Goose3, if available
    if Goose is not None:
        try:
            g = Goose({"browser_user_agent": "Mozilla/5.0"})
            content = g.extract(url=url)
            text = getattr(content, "cleaned_text", "") or ""
            date = getattr(content, "publish_date", None)
            if text:
                return text, date
        except Exception:
            pass
    # Final fallback to readability-lxml if both readability and BeautifulSoup are available
    if Document is not None and BeautifulSoup is not None:
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            doc = Document(resp.text)  # type: ignore[call-arg]
            # ``summary()`` returns HTML containing the main content【842996678366491†L94-L126】
            html_content = doc.summary()  # type: ignore[attr-defined]
            soup = BeautifulSoup(html_content, "html.parser")
            # Extract plain text from the HTML
            text = soup.get_text(separator="\n").strip()
            # readability-lxml does not provide a publish date; return None
            return text, None
        except Exception:
            pass
    # If all extractors fail or are unavailable, return empty text
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
        # Convert the HTML body to plain text.  If BeautifulSoup is unavailable,
        # fall back to returning the raw HTML.
        if html_body and BeautifulSoup is not None:
            text = BeautifulSoup(html_body, "html.parser").get_text(separator="\n").strip()
        else:
            text = html_body or ""
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

    # Configure the page and present a simplified search interface similar to
    # the Clippings dashboard.  Users enter a single client or topic and click
    # "Search" to fetch a report.  A UK coverage toggle is provided as a
    # placeholder but is not currently enforced.
    st.set_page_config(page_title="Media Monitoring Dashboard", layout="wide")
    st.title("Clippings‑style Media Monitoring Dashboard")

    query = st.text_input(
        "Which client or topic needs a report?",
        value="",
        placeholder="Enter a company, person or keyword"
    )
    uk_only = st.checkbox("UK coverage only", value=False)
    # Fixed number of articles per search for simplicity
    max_articles = 20
    if st.button("Search"):
        if query.strip():
            # Pass the UK toggle to the monitoring function.  Domain filtering is
            # not exposed in this simplified interface; to target specific
            # publications, users can enter domain names directly in the
            # keywords field using the ``site:`` syntax (e.g., "site:ft.com").
            run_monitoring(query, max_articles, "", uk_only)
        else:
            st.warning("Please enter at least one keyword or company name.")


def run_monitoring(
    query_string: str,
    max_articles: int,
    domains_input: str = "",
    uk_only: bool = False,
) -> None:
    """Run the monitoring process for a given set of queries.

    The simplified monitor retrieves all articles via Google News RSS.  Domain
    restrictions are respected using the ``site:`` operator, and users may
    optionally restrict results to UK publications via the ``uk_only`` flag.
    Articles are scraped for full text, scored and displayed in a card‑style
    layout.

    Parameters
    ----------
    query_string : str
        Comma‑separated keywords or company names to search for.
    max_articles : int
        Maximum number of articles to retrieve per keyword.
    domains_input : str, optional
        Comma‑separated list of publication names or domains to restrict the
        search to.  Names are mapped to domains using ``PUBLICATION_DOMAINS``.
    uk_only : bool, optional
        If True, restrict Google News results to UK sources by passing
        language and country parameters to the RSS feed.  Default is False.
    """
    with st.spinner("Fetching news articles…"):
        queries = [q.strip() for q in query_string.split(",") if q.strip()]
        all_articles: List[Dict] = []
        # Parse any domain restrictions or publication names from the argument.
        domain_list: List[str] = []
        for token in [d.strip() for d in domains_input.split(",") if d.strip()]:
            key = token.lower()
            if key in PUBLICATION_DOMAINS:
                domain_list.extend(PUBLICATION_DOMAINS[key])
            else:
                domain_list.append(token)
        # Remove duplicates while preserving order
        seen: set[str] = set()
        domain_list = [d for d in domain_list if not (d in seen or seen.add(d))]
        # Determine regional parameters based on UK coverage toggle
        if uk_only:
            hl = "en-GB"
            gl = "GB"
            ceid = "GB:en"
        else:
            hl = None
            gl = None
            ceid = None
        # Retrieve articles for each query
        for q in queries:
            # General Google News search
            articles = fetch_from_google_rss(q, limit=max_articles, hl=hl, gl=gl, ceid=ceid)
            all_articles.extend(articles)
            # Additional site‑specific searches
            for domain in domain_list:
                site_articles = fetch_from_google_site_search(
                    q,
                    domain,
                    days=7,
                    limit=max_articles,
                    hl=hl,
                    gl=gl,
                    ceid=ceid,
                )
                all_articles.extend(site_articles)
        if not all_articles:
            st.warning("No articles were found for the specified queries.")
            return
        # Scrape full text, derive sentiment and assign tiers
        enriched_results: List[Dict] = []
        for art in all_articles:
            url = art.get("url")
            # Use existing content if provided (should be rare with RSS)
            if art.get("content"):
                text = art["content"]
                pub_date = None
            else:
                text, pub_date = scrape_article(url) if url else ("", None)
            # Update missing publication date using scraped metadata
            if not art.get("publishedAt") and pub_date:
                if hasattr(pub_date, "isoformat"):
                    art["publishedAt"] = pub_date.isoformat()
                else:
                    art["publishedAt"] = str(pub_date)
            art["content"] = text
            # Sentiment analysis: use article body or description
            sentiment_label, sentiment_score = compute_sentiment(text or art.get("description", ""))
            art["sentiment"] = sentiment_label
            art["sentiment_score"] = sentiment_score
            # Tier classification based on source
            source_name = art.get("source", {}).get("name", "")
            art["tier"] = assign_tier(source_name) if source_name else None
            enriched_results.append(art)
        prioritised = prioritise_articles(enriched_results)
        # Display results with selection options
        st.subheader("Results")
        if not prioritised:
            st.info("No articles were found for the specified queries.")
            return
        display_count = min(len(prioritised), max_articles)
        # Collect selected articles indices in session state
        selected_indices = []
        for idx, art in enumerate(prioritised[:display_count], start=1):
            title = art.get("title") or "Untitled article"
            source_name = art.get("source", {}).get("name", "Unknown source")
            header = f"{idx}. {title} — {source_name}"
            with st.expander(header, expanded=False):
                pub_date = art.get("publishedAt") or "Unknown date"
                st.markdown(f"**Published:** {pub_date}")
                # Display scoring metrics
                st.markdown(
                    f"**Recency Score:** {round(art.get('recency', 0.0), 2)} | **Authority Score:** {round(art.get('authority', 0.0), 2)} | **Priority:** {round(art.get('priority', 0.0), 2)}"
                )
                # Display tier and sentiment (if available)
                tier_label = art.get("tier") or "Unclassified"
                sentiment_label = art.get("sentiment") or "N/A"
                st.markdown(f"**Tier:** {tier_label} | **Sentiment:** {sentiment_label}")
                description = art.get("description") or ""
                content_excerpt = (art.get("content", "") or "")[:500]
                snippet = description if description else content_excerpt
                if snippet:
                    st.write(snippet.strip() + ("…" if len(snippet) >= 500 else ""))
                st.markdown(f"[Read full article]({art.get('url')})")
                # Checkbox for including in the PDF
                include_key = f"include_{idx}"
                include_default = art.get("tier") in {"Top", "Mid", "Trade"}
                if st.checkbox("Include in report", value=include_default, key=include_key):
                    selected_indices.append(idx - 1)
        # Option to include sentiment column in PDF
        include_sentiment = st.checkbox("Include sentiment column in report", value=False)
        # Generate PDF button
        if st.button("Generate PDF Report"):
            # Gather selected articles by index
            selected_articles = [prioritised[i] for i in selected_indices if prioritised[i].get("tier")]
            if not selected_articles:
                st.warning("No articles selected or none fall into the defined tiers.")
            else:
                pdf_bytes = generate_pdf_report(selected_articles, include_sentiment)
                if pdf_bytes is None:
                    st.error("Report generation failed: ReportLab may not be installed.")
                else:
                    # Construct file name based on current date
                    date_tag = datetime.datetime.now().strftime("%Y-%m-%d")
                    filename = f"press_coverage_report_{date_tag}.pdf"
                    st.download_button(
                        label="Download PDF",
                        data=pdf_bytes,
                        file_name=filename,
                        mime="application/pdf",
                    )


if __name__ == "__main__":
    main()