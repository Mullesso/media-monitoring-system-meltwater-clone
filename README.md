# Media Monitoring System – Meltwater Clone

This repository contains a professional‑grade media monitoring dashboard built
with [Streamlit](https://streamlit.io).  It automatically searches for the
latest press releases and news articles related to user‑defined topics, then
scrapes and prioritises them based on recency and source credibility.  The
application is intended to provide quick insight into current events without
requiring any coding knowledge.

## Features

This release focuses on simplicity and polish while adding deeper insights
and professional report generation.  Key features include:

* **Single search bar with UK toggle** – a streamlined interface lets you
  type a topic, brand or person into one box and optionally restrict
  coverage to UK publications.  Under the hood the app queries the public
  [Google News RSS](https://news.google.com/rss) feed.  You can still
  employ advanced operators such as `site:` and `when:`【168391965472992†L183-L223】 to
  target specific outlets or date ranges.

* **Robust full‑text scraping** – when RSS entries lack article bodies, the
  app retrieves the full page and extracts the main content using
  **newspaper3k**, **goose3** and **readability‑lxml** in succession【275271027204652†L203-L371】【842996678366491†L94-L126】.
  This multi‑extractor approach ensures that most articles are readable.

* **Relevance and authority scoring** – each story is scored for recency
  (newer stories score higher) and source credibility.  The scoring
  guidelines are inspired by the News Literacy Project’s recommendations
  on evaluating standards, transparency and corrections policies【559532761496453†L84-L109】.

* **Sentiment analysis** – a lightweight sentiment model (VADER) analyses
  each article’s text.  VADER is a lexicon‑ and rule‑based sentiment
  analyser designed for social media and general text; it produces a
  compound score from ‑1 (very negative) to 1 (very positive)【126899030742881†L284-L304】.
  We convert this score into *positive*, *neutral* or *negative* labels and
  display them alongside each article.  Sentiment can also be optionally
  included in the generated PDF.

* **Tier classification** – publications are grouped into **Top**, **Mid**
  and **Trade/Industry** tiers based on their editorial reputation and
  scope.  Major global outlets like Reuters and the Financial Times
  comprise the Top tier; national papers such as The Times and The
  Telegraph fall into Mid; and specialist titles like Mining Weekly and
  Energy Voice are grouped under Trade.  Blogs and unknown sources are
  excluded from reports to maintain quality.

* **Interactive selection and PDF report** – after performing a search,
  results are displayed in expandable cards with checkboxes.  You can
  choose which articles to include in a professionally styled PDF report.
  The report reproduces the layout of the provided Word template: a
  striking header image, a grey “Press Coverage” bar, the current date
  and logo, grouped tables for each tier and a footer with contact
  icons.  Reports are generated on demand via ReportLab and offered as
  downloads.  A toggle lets you include the sentiment column in the
  report if desired.

* **No API keys required** – all data is sourced from public RSS feeds, so
  there are no secrets to manage.  Installation and deployment are
  straightforward.

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

5. **Select articles and generate a PDF** – After running a search, tick
   the “Include in report” boxes for the articles you wish to keep.
   Optionally enable “Include sentiment column in report” and click
   *Generate PDF Report*.  Once the report is ready you’ll see a
   download button to save the PDF locally.

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