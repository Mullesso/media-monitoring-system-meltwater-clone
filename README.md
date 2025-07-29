# Media Monitoring System – Meltwater Clone

This repository contains a professional‑grade media monitoring dashboard built
with [Streamlit](https://streamlit.io).  It automatically searches for the
latest press releases and news articles related to user‑defined topics, then
scrapes and prioritises them based on recency and source credibility.  The
application is intended to provide quick insight into current events without
requiring any coding knowledge.

## Features

* **Automated searching** – the app queries either the [NewsAPI](https://newsapi.org)
  or (if no API key is available) the publicly available Google News RSS feed.
  The [Google News RSS format](https://friendlyuser.github.io/posts/tech/net/news_app_csharp/)
  allows you to search for news articles by keyword by constructing a URL like
  `https://news.google.com/rss/search?q=YOUR_QUERY`【739508586957365†L26-L40】.
* **Full‑text scraping** – articles are downloaded with the [`newspaper3k`]
  library to extract their full text and publication date.  If extraction fails
  (some sites block scrapers) the app still shows the headline and link.
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

4. **Run the app**:

   ```bash
   streamlit run app.py
   ```

5. **Interact with the dashboard** – use the sidebar to enter keywords,
   adjust the number of articles per keyword and click *Search* to refresh
   results.  Click on a row in the results table or change the index in the
   number input to view the full text and details.

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

4. **Deploy**.  Streamlit will automatically build and launch your app.  You
   can share the public URL with colleagues or stakeholders.  If you need to
   update the app later, simply commit and push changes to your GitHub
   repository; Streamlit Cloud will re‑deploy automatically.

## Adding additional data sources

This application is intentionally modular.  The `fetch_from_newsapi` and
`fetch_from_google_rss` functions encapsulate the retrieval logic.  You can
extend the system by adding functions that call other APIs or scrape
industry‑specific feeds.  To plug new results into the ranking algorithm,
ensure each returned dictionary contains at least `title`, `url`, `source.name`
and `publishedAt` keys.  The recency and authority functions will handle the
rest.

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