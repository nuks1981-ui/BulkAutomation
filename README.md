# BulkAutomation

Downloads the CRM last-event report from the India Post MIS Reports portal
(https://app.indiapost.gov.in/misreports/crm-last-event) for a date
range/customer ID, and processes it into customized Excel/CSV output
(filtered & reshaped columns, an aggregated summary sheet, optionally split
into multiple files, optionally merged with your own reference data).

**This must run somewhere that can reach `app.indiapost.gov.in`** — your own
PC or a server you control. It will not run inside a cloud sandbox that
blocks that domain.

## 1. Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env            # fill in your India Post username/password
cp config/selectors.example.yaml config/selectors.yaml
cp config/pipeline.example.yaml config/pipeline.yaml
```

`.env` and `config/selectors.yaml` are gitignored — never commit real
credentials or filled-in selectors that might reveal internal portal
structure alongside credentials.

## 2. Discover the real form fields (one-time)

The exact field IDs on the India Post login/report screens aren't known yet.
Run:

```bash
python scripts/discover_form.py
```

A visible Chromium window opens. **You** log in and click through to the
report filter screen (this also handles any CAPTCHA). At each checkpoint,
press Enter in the terminal — the script saves a JSON dump of every
input/select/button on that page plus a screenshot, under
`data/discovery/`.

Share those JSON files back (paste the contents, or the relevant field
entries) so `config/selectors.yaml` can be filled in with the real
selectors, replacing the `TODO` placeholders.

## 3. Fill in `config/pipeline.yaml`

Open one of the CSVs downloaded during discovery (or run step 4 once
selectors are filled in) to see the real column headers, then edit
`config/pipeline.yaml`:
- `columns` — which columns to keep & rename
- `filters` — which rows to keep
- `aggregate` — group-by summary sheet
- `split_by` — split output into one file per value of a column
- `merge` — left-join against your own reference file
- `output` — xlsx or csv, filename prefix

## 4. Run it

```bash
python -m src.pipeline --from-date 01/08/2026 --to-date 23/08/2026
```

Defaults to yesterday→today if dates are omitted. Customer ID comes from
`INDIAPOST_CUSTOMER_ID` in `.env`, or pass `--customer-id`.

Output lands in `data/processed/`.

To re-process an already-downloaded file without hitting the site again:

```bash
python -m src.pipeline --skip-download --raw-file data/raw/whatever.csv
```

## 5. Schedule it (recurring runs)

**Linux/macOS (cron)** — daily at 7am, previous day's data:

```cron
0 7 * * * cd /path/to/BulkAutomation && venv/bin/python -m src.pipeline --from-date "$(date -d yesterday +\%d/\%m/\%Y)" --to-date "$(date +\%d/\%m/\%Y)" >> logs/pipeline.log 2>&1
```

**Windows (Task Scheduler)** — create a task that runs:
```
C:\path\to\BulkAutomation\venv\Scripts\python.exe -m src.pipeline
```
with "Start in" set to the project directory. The default date range
(yesterday→today) applies automatically if you don't pass `--from-date`/`--to-date`.

Set `HEADLESS=true` in `.env` for scheduled/unattended runs.

## CAPTCHA caveat

If the India Post login page shows a CAPTCHA, **fully unattended scheduled
runs will not be able to get past it** — no bypass is built here, since
defeating a site's anti-automation challenge isn't something this project
does. If that's the case, options are: check whether the portal offers a
"remember this browser" / longer-lived session cookie you can reuse, or run
the pipeline as a semi-attended task where you solve the CAPTCHA once when
prompted.

## Project layout

```
src/config.py     Loads .env into a Settings object
src/browser.py    Generic Playwright step-executor, driven by config/selectors.yaml
src/process.py    pandas pipeline: filter/reshape -> aggregate -> split -> merge -> export
src/pipeline.py   CLI entry point (download + process)
scripts/discover_form.py  One-time interactive tool to capture real form field selectors
config/           selectors.yaml (site form fields) + pipeline.yaml (data processing rules)
data/raw/         Downloaded reports (gitignored)
data/processed/   Final output files (gitignored)
data/discovery/   Discovery dumps from discover_form.py (gitignored)
```
