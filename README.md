# Media Monitoring System – Meltwater Clone

This repository contains a professional‑grade media monitoring dashboard built
with [Streamlit](https://streamlit.io).  It automatically searches for the
latest press releases and news articles related to user‑defined topics, then
scrapes and prioritises them based on recency and source credibility.  The
application is intended to provide quick insight into current events without
requiring any coding knowledge.

## Features

* **Automated searching** – the app queries a variety of sources to capture as
  many relevant stories as possible:

  * **NewsAPI** – if you provide a `NEWS_API_KEY`, the app calls the
    [NewsAPI](https://newsapi.org) for high‑quality news results; otherwise it
    falls back to the publicly available Google News RSS feed.  The
    [Google News RSS format](https://friendlyuser.github.io/posts/tech/net/news_app_csharp/)
    allows you to search for news articles by keyword by constructing a URL like
    `https://news.google.com/rss/search?q=YOUR_QUERY`【739508586957365†L26-L40】.
  * **GDELT** – the app queries the [GDELT DOC 2.0 API](https://api.gdeltproject.org/api/v2/doc/doc) in
    *artlist* mode, which monitors global news sources in 65 languages and
    machine‑translates them to English【317432739810327†L52-L63】.  This greatly expands
    coverage beyond mainstream English‑language outlets.
  * **The Guardian** – if you supply a `GUARDIAN_API_KEY`, the app calls
    The Guardian’s Open Platform to retrieve full articles from the Guardian’s
    archive.  A free developer key grants up to 500 calls per day and includes
    access to the full body text of each article【666270658916805†L21-L35】.  The API
    supports the `show-fields=body` filter to return article body text directly
    【555774334167872†L49-L53】, so there is no need to scrape Guardian pages.

  Results from all sources are combined and de‑duplicated before scoring.
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
* **Streamlit dashboard** – results are displayed in an interactive table with
  sortable columns.  You can drill into any article to read the extracted
  text and link back to the original site.
* **Customisable keywords** – enter your own topics, company names or phrases in
  the sidebar separated by commas.  Adjust the number of articles per
  keyword with a slider.
* **Domain and publication filtering** – optionally restrict searches to specific
  news outlets by entering either domain names (e.g., `reuters.com,bloomberg.com`) or
  human‑readable publication names (e.g., `The Times, Daily Mail`) in the
  sidebar.  The app looks up publication names in a built‑in mapping
  (`PUBLICATION_DOMAINS` in `app.py`) and translates them into domain
  filters.  It then uses the Google News `site:` search operator combined
  with a recency filter (e.g., `when:7d`) to build RSS feeds for each domain
  【168391965472992†L183-L223】.  This lets you focus on outlets such as The Times,
  The Telegraph, Daily Mail, Mining Review Africa, Mining Weekly, Mining
  Journal, Mining Magazine, Mining.com, Energy Voice, Upstreamonline.com,
  Financial Times, Reuters or Bloomberg.
* **Secure secret management** – API keys are never hard‑coded.  Store your
  `NEWS_API_KEY` in the `.streamlit/secrets.toml` file or as an environment
  variable; the app reads it automatically.  Streamlit’s secret management
  documentation recommends using environment variables instead of embedding
  keys in code【10524337110845†L214-L264】.

## Getting started locally

1. **Clone this repository** (or download the ZIP).
2. **Install dependencies**:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. **Add your NewsAPI key** (optional but strongly recommended):

   Create a file called `.streamlit/secrets.toml` in the root of the
   repository with the following contents:

   ```toml
   # .streamlit/secrets.toml
   NEWS_API_KEY = "your_api_key_here"
   ```

   You can register for a free key at [newsapi.org](https://newsapi.org) and
   paste it here.  Without a key the app falls back to the Google News RSS
   feed, which may return fewer results.

4. **Optionally add a Guardian API key**:

   To search The Guardian’s archive and receive the full body of each article
   without scraping, register for a free developer key on
   [The Guardian Open Platform](https://open-platform.theguardian.com/).  Then
   add a second line to your `.streamlit/secrets.toml` file:

   ```toml
   GUARDIAN_API_KEY = "your_guardian_key_here"
   ```

   The developer key allows up to 500 calls per day and includes access to the
   full article body【666270658916805†L21-L35】.  The app uses the `show-fields=body`
   filter to retrieve article text directly from the API【555774334167872†L49-L53】.

5. **Run the app**:

   ```bash
   streamlit run app.py
   ```

6. **Interact with the dashboard** – use the sidebar to enter keywords,
   adjust the number of articles per keyword, optionally specify
   comma‑separated domain names or publication names (e.g., `reuters.com,dailymail.co.uk` or
   `The Times, Mining Weekly`) to restrict searches, and click *Search* to
   refresh results.  The app maps publication names to the appropriate
   domains internally.  Click on a row in the results table or change the
   index in the number input to view the full text and details.

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
3. **Configure secrets**: after creating the app, open the *Secrets* tab on
   Streamlit Cloud and add your `NEWS_API_KEY` as follows (one key per line):

   ```toml
   NEWS_API_KEY = "your_api_key_here"
   ```

   To include The Guardian archive, also add your `GUARDIAN_API_KEY` on a
   separate line:

   ```toml
   GUARDIAN_API_KEY = "your_guardian_key_here"
   ```

4. **Deploy**.  Streamlit will automatically build and launch your app.  You
   can share the public URL with colleagues or stakeholders.  If you need to
   update the app later, simply commit and push changes to your GitHub
   repository; Streamlit Cloud will re‑deploy automatically.

## Adding additional data sources

This application is intentionally modular.  The `fetch_from_newsapi`,
`fetch_from_google_rss`, `fetch_from_gdelt` and `fetch_from_guardian` functions
encapsulate retrieval logic.  You can extend the system by adding new
functions that call other APIs, RSS feeds or custom scrapers.  To plug new
results into the ranking algorithm, ensure each returned dictionary contains
at least `title`, `url`, `source.name`, `publishedAt` and (optionally)
`content` keys.  The recency and authority functions will handle the rest.

When adding API integrations, check whether the service provides full article
bodies.  For example, The Guardian API exposes a `show-fields=body` filter
that returns the article body directly【555774334167872†L49-L53】, whereas GDELT
returns only URLs and metadata.  For services that provide no body text, the
application will automatically scrape the articles using its multi‑stage
extractor chain.

By default the app queries GDELT’s DOC 2.0 API in “ArtList” mode, which
returns a list of article URLs and metadata for stories published in the last
three months【317432739810327†L21-L63】.  You can adjust the `max_records` and
`timespan` parameters in `fetch_from_gdelt` to control how many results are
returned and over what time window.

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