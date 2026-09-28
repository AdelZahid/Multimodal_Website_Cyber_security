# Multimodal Website Cybersecurity — Data Collection

> A multimodal machine learning framework for website cybersecurity analysis
> using URL, HTML, text, and third-party features. Fine-tuned SBERT provides
> 384-dimensional semantic embeddings, combined with statistical features.
> XGBoost, Random Forest, LightGBM, and stacking predict website risk,
> category, and activity.

**This directory holds the data-collection stage of that pipeline** — the
scraper that gathers the raw multimodal corpus the models train on. The
embedding, feature-engineering, and model-training stages live elsewhere in
the project.

---

# Website Dataset Scraper

A multi-threaded web scraper that downloads web pages, extracts clean visible
text, records third-party resources, and builds a structured dataset on disk.

Each collected page produces three artefacts on disk plus one CSV row that
indexes them.

---

## Requirements

- **Python 3.10 or newer.** The scraper code itself needs 3.10+ (`requests`,
  `urllib3`, and `playwright` all declare `>=3.10`). Verified working on
  **Python 3.14.6**.
- **Python 3.12+ if you install `requirements.txt` as-is**, because that file
  pins `numpy 2.5.1` (`>=3.12`) and `pandas 3.0.5` (`>=3.11`). Neither is
  imported anywhere in the code — see [Unused dependencies](#unused-dependencies).

| Package | Purpose | Needed? |
|---|---|---|
| `requests` | HTTP downloading | Yes |
| `beautifulsoup4` | HTML parsing | Yes |
| `lxml` | Parser backend for BeautifulSoup (`config.HTML_PARSER`) | Yes |
| `urllib3` | Connection pooling / retry adapter | Yes |
| `playwright` | Browser fallback for JS-heavy pages | Only for `--playwright` |

### Unused dependencies

`requirements.txt` also pins `numpy`, `pandas`, `tldextract`, `structlog`,
`backoff`, `ratelimit`, `python-dotenv`, and `filelock`. **None of them are
imported by any module in the live pipeline** — they are leftovers from an
earlier design and can be deleted. They are also the reason the file needs
Python 3.12+ instead of 3.10.

Note that `structlog`, `backoff`, `ratelimit`, and `python-dotenv` are not
even present in the checked-in `venv/`, so the current environment was not
built from this file as written.

---

## Setup

Run all commands from the project root.

```bash
# 1. Create and activate a virtual environment

# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt
```

### Optional: Playwright fallback

Only needed if you want `--playwright` (it renders JavaScript for pages that
return little or no HTML to a plain HTTP request).

```bash
pip install playwright
playwright install chromium
```

Without it, the scraper still works — it just logs
`Playwright not installed; skipping browser fallback` and moves on.

---

## Adding URLs

Put one URL per line in a text file. Blank lines and lines starting with `#`
are ignored.

```
urls/
├── malicious_urls.txt   # default input (562 URLs)
└── urls.txt             # empty — put general/benign URLs here
```

```text
# urls/urls.txt
https://example.com/
https://www.iana.org/domains/reserved

# comments are allowed
```

`hxxp://` and `hxxps://` obfuscation is decoded automatically.

The default input file is `urls/malicious_urls.txt` (set by `URL_FILE` in
`config.py`). Point at a different file with `--urls-file`.

---

## Running

### Quick start

```bash
python main.py
```

### Always test with a dry run first

Loads, validates, and de-duplicates the URLs without downloading anything:

```bash
python main.py --dry-run
```

### Other useful invocations

```bash
# Use a different URL list
python main.py --urls-file urls/urls.txt

# Scrape with 8 threads and 2 retries
python main.py --workers 8 --max-retries 2

# Also extract source-code blocks from <pre>/<code>/<script> tags
python main.py --source-code

# Fall back to a real browser for pages that return stub HTML
python main.py --playwright

# Ignore the checkpoint and re-scrape everything from scratch
python main.py --clear-checkpoint

# Verbose logging
python main.py --log-level DEBUG
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--urls-file PATH` | `urls/malicious_urls.txt` | URL list to read |
| `--workers`, `-w` | `16` | Worker threads |
| `--max-retries`, `-r` | `1` | Download attempts per URL |
| `--timeout`, `-t` | `5` | Per-request timeout (seconds) |
| `--playwright` | off | Browser fallback for failed/stub pages |
| `--source-code` | off | Extract source-code blocks |
| `--no-ssl` | off | Disable SSL certificate verification |
| `--dry-run` | off | Validate URLs, download nothing |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--clear-checkpoint` | off | Reprocess URLs already in the checkpoint |

### Simplified runner

`simple_run.py` runs with the defaults from `config.py` and no CLI flags:

```bash
python simple_run.py
```

---

## Output

```
WebsiteDataset/
├── dataset.csv          # one row per collected page (the index)
├── html/000001.html     # raw HTML as served
├── text/000001.txt      # cleaned visible text
└── thirdparty/000001.json
```

Plus, at the project root:

| File | Purpose |
|---|---|
| `checkpoint.json` | URLs already processed — enables resume |
| `failed_urls.csv` | URLs that failed, with the error reason |
| `logs/scraper.log` | Full run log |

### `dataset.csv` schema

| Column | Description |
|---|---|
| `id` | 6-digit zero-padded sequence number |
| `url` | Requested URL (normalised) |
| `final_url` | URL after redirects |
| `http_status` | HTTP response code |
| `html_file` | Relative path to the saved HTML |
| `text_file` | Relative path to the extracted text |
| `thirdparty_file` | Relative path to the third-party JSON |
| `risk` | *Reserved — always empty (see below)* |
| `category` | *Reserved — always empty (see below)* |
| `illicit_activity_type` | *Reserved — always empty (see below)* |
| `text_length` | Character count of the extracted text |
| `collected_at` | Collection date (`YYYY-MM-DD`) |

> **About the three empty columns.** An earlier version of this project
> included a rule-based content classifier that assigned `risk`, `category`,
> and `illicit_activity_type` inside the scraper. That logic has been removed:
> those labels are now produced by the modelling stage of the pipeline (SBERT
> embeddings + statistical features → XGBoost / Random Forest / LightGBM /
> stacking), so the scraper does not write them.
>
> The columns are kept in the schema so the CSV stays compatible with
> already-collected rows — they are written as empty for all new rows, and
> existing values are never modified. If you want a clean schema, drop those
> three names from `DATASET_FIELDS` in `enhanced_scraper.py` and migrate the
> existing CSV.

---

## How it works

1. **Load & filter** — read the URL file, discard invalid entries, normalise,
   de-duplicate.
2. **Skip what is already done** — URLs present in `dataset.csv` or in
   `checkpoint.json` are skipped, so re-running is safe and cheap.
3. **Download** — via a thread-local `requests.Session` with connection
   pooling, a rotating pool of five user agents, exponential backoff between
   retries, and a full User-Agent retry sweep on `403`/`429`.
4. **Extract** — visible text is pulled with BeautifulSoup, stripping
   `script`, `style`, `noscript`, `svg`, `canvas`, `iframe`, `header`,
   `footer`, comments, and hidden elements.
5. **Third-party analysis** — external scripts, stylesheets, iframes, images,
   links and media are collected by comparing each resource's registered
   domain against the page's own, along with form actions/inputs, analytics
   endpoints, and ad/social widgets.
6. **Persist** — HTML, text, and the third-party JSON are written per ID, and
   a CSV row is appended. Results flush every 50 URLs and again at the end, so
   an interrupted run keeps what it already collected.

### Resuming an interrupted run

Just run the same command again. Completed URLs are skipped via
`checkpoint.json` and `dataset.csv`. Use `--clear-checkpoint` to override this.

---

## Configuration

Edit `config.py` for persistent settings:

| Setting | Default | Description |
|---|---|---|
| `URL_FILE` | `urls/malicious_urls.txt` | Default input file |
| `MAX_WORKERS` | `16` | Thread count |
| `REQUEST_TIMEOUT` | `5` | Seconds per request |
| `MAX_RETRIES` | `1` | Attempts per URL |
| `RATE_LIMIT_DELAY` | *not set* → `2` | Retry backoff base, in seconds |
| `VERIFY_SSL` | `False` | Verify certificates (see the warning below) |
| `ID_PADDING` | `6` | Digits in the dataset ID |
| `SAVE_HTML` / `SAVE_TEXT` / `SAVE_THIRDPARTY` | `True` | Toggle artefacts |
| `SAVE_CHECKPOINT` | `True` | Toggle checkpointing |
| `HTML_PARSER` | `lxml` | BeautifulSoup parser |

Two things about this table are worth knowing:

- **`RETRY_DELAY = 2` in `config.py` is dead.** It is only read by the unused
  `modules/downloader.py`. The live code reads **`RATE_LIMIT_DELAY`**, which is
  *not defined in `config.py`* and therefore falls back to a hard-coded `2`
  inside `enhanced_scraper.py`. To change the backoff, add
  `RATE_LIMIT_DELAY = <seconds>` to `config.py`. You can leave `RETRY_DELAY`
  alone or delete it.
- **`CHECKPOINT_INTERVAL` is not in `config.py` either.** Results are flushed
  to CSV every 50 URLs via a `getattr` default in `enhanced_scraper.py`. Define
  `CHECKPOINT_INTERVAL` in `config.py` to change it.

> ### SSL caveat: `main.py` overrides `config.VERIFY_SSL`
>
> `main.py` passes `verify_ssl=not args.no_ssl` to `EnhancedScraper`. Because
> that is never `None`, it **overrides** the config default. The practical
> effect:
>
> | Entry point | SSL verification |
> |---|---|
> | `python main.py` | **ON** — `config.VERIFY_SSL = False` is ignored |
> | `python main.py --no-ssl` | OFF |
> | `python simple_run.py` | OFF — falls back to `config.VERIFY_SSL` |
>
> Given that a large share of the target URLs use self-signed or invalid
> certificates, running `python main.py` as-is will reject many of them. Either
> always pass `--no-ssl`, or fix `main.py` to respect the config value.

Lowering `REQUEST_TIMEOUT` and raising `MAX_RETRIES` usually improves coverage
on slow or flaky hosts. Adding `--source-code` increases run time and output
size noticeably.

---

## Project layout

```
website_dataset/
├── main.py                  # CLI entry point
├── simple_run.py            # no-flag runner
├── enhanced_scraper.py      # EnhancedScraper — the core
├── config.py                # all tunable settings
├── modules/
│   ├── utils.py             # URL validation, normalisation, file writers  [used]
│   ├── text_extractor.py    # HTML -> clean visible text                    [used]
│   ├── checkpoint.py        # resume support                                [used]
│   ├── downloader.py        # legacy, not imported                          [unused]
│   └── thirdparty.py        # legacy, not imported                          [unused]
├── urls/
│   ├── malicious_urls.txt   # input URLs (the default file)
│   └── urls.txt             # input URLs (empty)
└── WebsiteDataset/          # generated output
```

`modules/downloader.py` and `modules/thirdparty.py` are older standalone
modules that nothing imports — `EnhancedScraper` has its own inline
implementations of both. They are safe to delete.

---

## Known issue: leaked credentials in captured pages

**Scraped pages can contain live third-party secrets, and this dataset does.**

A full scan of the 762 captured pages found credentials belonging to other
people's systems:

| Finding | Occurrences | Files |
|---|---|---|
| Google/GCP API key | 69 | 33 |
| JWT-looking token | 90 | 18 |
| Twilio account SID | 3 | 1 (`000660`, `000710`) |
| Groq API key | 2 | 1 (`000660`) |
| AWS access key ID | 1 | 1 (`000168`) |
| OpenAI key | 1 | 1 (`000563`) |
| Firebase project URL | 2 | 2 |

The clearest case is `html/000660.html`, a captured storefront whose
client-side configuration JSON leaks a **working API key belonging to that
store's operator** — a credential a third party never intended to publish.

Severity is not uniform. An `AKIA…` key ID without its paired secret, a
Firebase URL, or a domain-restricted client-side Google key are public
identifiers by design and are not directly exploitable. The Groq key and any
live JWT session tokens are a different matter.

### Why `WebsiteDataset/` is not committed

GitHub push protection blocks the push outright (`GH013: Push cannot contain
secrets`), and the offered "allow this secret" links would publish live
credentials to a public repository. They should not be used.

### Before publishing the dataset

1. Redact the secret values in place, keeping page structure and JSON shape —
   the features the models consume do not depend on the values.
2. Re-scan to confirm nothing remains.
3. Only then commit the folder.

Note that a fresh scrape re-captures these. Treat redaction as a recurring step
in the collection pipeline, not a one-off.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'modules'`**
Run from the project root, and make sure the virtual environment is active.

**`ModuleNotFoundError: No module named 'requests'` (or `bs4`, `lxml`)**
The virtual environment is active but dependencies are missing:
`pip install -r requirements.txt`.

**`InsecureRequestWarning`**
Expected whenever SSL verification is off. Note that `python simple_run.py`
uses `config.VERIFY_SSL = False` and will emit this, whereas `python main.py`
verifies by default (see the [SSL caveat](#configuration)) — so you may see this
warning from one entry point and not the other. Set `VERIFY_SSL = True` in
`config.py` if you only want to scrape hosts with valid certificates.

**Most URLs land in `failed_urls.csv`**
Usually a timeout that is too aggressive for slow hosts. Try
`--timeout 15 --max-retries 3`. Sites that return JS-only stubs need
`--playwright`.

**Pages scraped but almost empty**
They are JS-rendered. Re-run those URLs with `--playwright`.

**Nothing gets scraped on a re-run**
Everything is already in `dataset.csv` or `checkpoint.json`. This is the
intended resume behaviour — use `--clear-checkpoint` to force a re-scrape.
