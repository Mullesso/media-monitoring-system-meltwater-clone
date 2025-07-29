# Media Monitoring System – Meltwater Clone

This repository contains a professional‑grade media monitoring dashboard built
with [Streamlit](https://streamlit.io).  It automatically searches for the
latest press releases and news articles related to user‑defined topics, then
scrapes and prioritises them based on recency and source credibility.  The
application is intended to provide quick insight into current events without
requiring any coding knowledge.

## Features

The current version of the media monitoring dashboard has been streamlined to
prioritise ease of use and reliability.  It focuses on a single source of
news, uses a robust multi‑stage scraper and presents results in a clean,
Clippings‑style interface:

* **Google News RSS search** – the app retrieves articles from the public
  [Google News RSS](https://news.google.com/rss) feed for any keyword or
  phrase.  You can restrict results to UK sources by enabling the “UK
  coverage only” toggle on the home page.  Internally this sets the
  appropriate `hl=en-GB`, `gl=GB` and `ceid=GB:en` parameters on the RSS
  request.  The RSS format allows advanced operators such as `site:` and
  `when:`【168391965472992†L183-L223】.  For example, entering `site:reuters.com AI
  startups` searches for “AI startups” articles on Reuters only, while
  `When:1d Beyonce` finds stories about Beyoncé from the past day.  See
  Google’s operator reference for more ideas.

* **Full‑text scraping** – when the RSS feed does not contain the article
  body, the app downloads each page and extracts the main content using a
  series of extractors.  It first uses **newspaper3k**, falls back to
  **goose3** when necessary【275271027204652†L203-L371】 and finally applies **readability‑lxml**
  with BeautifulSoup【842996678366491†L94-L126】.  This multi‑stage approach
  maximises the chance of obtaining readable text.

* **Relevance and authority scoring** – each article receives a recency
  score (fresh stories within seven days score highest) and a source
  credibility score based on a curated list of reputable outlets.  The
  News Literacy Project advises evaluating news sources based on standards,
  transparency and corrections policies【559532761496453†L84-L109】; outlets like Reuters
  and the BBC score highest in our heuristic.

* **Clean Streamlit dashboard** – the interface features a single
  search bar inspired by the Clippings design.  Enter a topic, brand or
  person, enable UK coverage if desired, and click *Search*.  Results are
  displayed in expandable cards that show the headline, publication date,
  recency and authority scores, a short excerpt and a link to the full
  article.

* **Optional domain filtering via search syntax** – rather than exposing a
  separate domain input, you can restrict results to specific outlets by
  including their domains directly in the search query using the `site:`
  operator (e.g., `site:bloomberg.com mergers and acquisitions`).  If you
  wish to search multiple outlets, separate them with spaces (e.g.,
  `site:reuters.com site:ft.com fintech`).  Behind the scenes the app uses
  the Google News RSS feed with your exact search string, so all standard
  operators are available【168391965472992†L183-L223】.

All results are deduplicated, scraped, scored and presented together.  The
application no longer depends on external API keys, making setup much
simpler.
* **Full‑text scraping** – when an API does not provide full article text,
  the app downloads the page and extracts the main body using a series of
  fallbacks:

  * **newspaper3k** – a widely used content extractor based on lxml’s HTML
    cleaner.  It works on many mainstream news sites but may fail on some
    layouts or when sites block scrapers.
  * **goose3** – an Apache‑licensed extractor that returns the main body,
    metadata and images【275271027204652†L203-L371】.  It serves as a second attempt
    when newspaper3k does not return text.
  * **readability‑lxml** – a Python port of the Readability algorithm that
    extracts the main content from any web page【842996678366491†L94-L126】.  As a
    final fallback, the app uses readability and then converts the HTML to
    plain text using BeautifulSoup.  This ensures that most articles have at
    least some extracted text.

  Articles retrieved from The Guardian API already include the body text
  (via the `show-fields=body` filter【555774334167872†L49-L53】) and therefore bypass
  scraping.
* **Relevance and authority scoring** – each article receives a recency score
  (fresh stories within seven days score highest) and a source credibility
  score based on a hand‑curated list of reputable news outlets.  The News
  Literacy Project suggests looking for standards, transparency and
  accountability when vetting a news source【559532761496453†L84-L109】; sources
  such as Reuters, the Associated Press and the BBC rank highest.
* **Clean Streamlit dashboard** – results are presented in expandable cards
  inspired by the Clippings design.  Each card shows the headline,
  publication date and scores, along with a short excerpt and a link to
  the full article.
* **Single search bar** – simply enter a topic, brand or person into the
  search field on the home page.  There is no sidebar or slider.  Click
  *Search* to fetch up to 20 articles.
* **Domain filtering via search syntax** – you can focus on particular
  outlets by using the `site:` operator directly in your search query, e.g.
  `site:ft.com mergers` or `site:reuters.com site:bloomberg.com fintech`.  All
  Google News operators are supported【168391965472992†L183-L223】.  There is no longer
  a separate sidebar field for domains, making the interface cleaner.

* **No API keys required** – the simplified application relies solely on
  publicly available Google News RSS feeds.  You do not need to register
  or supply any API keys.

## Getting started locally

1. **Clone this repository** (or download the ZIP).
2. **Install dependencies**:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. **Run the app**:

   ```bash
   streamlit run app.py
   ```

4. **Interact with the dashboard** – open
   [http://localhost:8501](http://localhost:8501) in your browser.  Type a
   keyword, brand or person into the search bar, enable “UK coverage only” if
   you want to restrict to UK publications, and click *Search*.  Use
   advanced operators like `site:reuters.com` or `when:3d` directly in the
   search bar to filter results.  Expand any result card to read an excerpt
   and follow the link to the full article.

### Customising source authority

The authority scoring is defined in `app.py` inside the `authority_score`
function.  You can modify the `authoritative_outlets` dictionary to suit your
needs by adding, removing or adjusting the scores for different sources.  The
News Literacy Project recommends evaluating sources based on ethical standards,
transparency and how they handle errors【559532761496453†L84-L109】.  Unknown
sources are assigned a modest default score.

## Deployment to Streamlit Cloud

1. **Fork or upload this repository** to your own GitHub account.
2. **Create a new app** on [Streamlit Community Cloud](https://streamlit.io/cloud).
   Connect it to your forked repository and select the `app.py` file as the
   entrypoint.
3. **Deploy**.  Streamlit will automatically build and launch your app.
   There are no secrets to configure because the app uses only the Google
   News RSS feed.  Share the public URL with colleagues or stakeholders.
   Whenever you update the repository, Streamlit Cloud will re‑deploy
   automatically.

## Adding additional data sources

This application remains modular.  The core retrieval happens via
`fetch_from_google_rss`, and domain‑specific searches are handled by
`fetch_from_google_site_search`.  To extend the system with additional
sources (e.g., a licensed news API or a custom scraper), add a new
function that returns a list of dictionaries with at least the `title`,
`url`, `source.name` and `publishedAt` keys.  You can then merge those
results into the `all_articles` list inside `run_monitoring`.  The scoring
and display logic will handle the rest.

## Ethical and legal considerations

* **Respect terms of service** – the Google News RSS feed is used here for
  demonstration purposes.  Google’s terms prohibit scraping or re‑publishing
  their content without permission【739508586957365†L40-L45】.  Use the NewsAPI
  or other licensed sources for production systems.
* **Evaluate sources** – always cross‑check important information against
  multiple reputable sources.  The News Literacy Project advises verifying
  the standards, transparency and corrections policies of news outlets
  before trusting their content【559532761496453†L84-L109】.
* **Secure your API keys** – never commit API keys or secrets to public
  repositories.  Instead, store them as environment variables or secrets as
  recommended by Streamlit’s security guidance【10524337110845†L214-L264】.

## License

This project is open source under the MIT License.  See the `LICENSE` file for
details.