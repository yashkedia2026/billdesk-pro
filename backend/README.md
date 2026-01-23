# Bill Generator Backend (Step 6)

## Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload --port 8001
```

Open http://localhost:8001/ in your browser.

## Generate PDF

`/generate` returns a PDF by default. Use `?debug=true` to get JSON instead.

Download a PDF:

```bash
curl -o Bill_demo_2026-01-20.pdf -X POST "http://localhost:8001/generate" \
  -F "account=demo" \
  -F "trade_date=2026-01-20" \
  -F "daywise_file=@\"sample_data/20.01.2026 DAY WISE 13516.csv\"" \
  -F "netwise_file=@\"sample_data/20.01.2026 NET WISE 13516.csv\""
```

Debug JSON:

```bash
curl -X POST "http://localhost:8001/generate?debug=true" \
  -F "account=demo" \
  -F "trade_date=2026-01-20" \
  -F "daywise_file=@\"sample_data/20.01.2026 DAY WISE 13516.csv\"" \
  -F "netwise_file=@\"sample_data/20.01.2026 NET WISE 13516.csv\""
```

## Health Check

```bash
curl http://localhost:8001/health
```

## Rate Card

- Default location: `backend/config/rate_card.xlsx`
- Fallback: `backend/config/FO CHARGES FORMULA.xlsx` if present
- Override with env var: `RATE_CARD_PATH=/path/to/rate_card.xlsx`
- Ensure TOC rates in the sheet match the broker PDF conventions (NSE 0.0505, BSE 0.0495 for the current sample PDFs).

## Charges Debug (Step 3)

Local debug script (prints charges JSON using sample data):

```bash
python -m app.scripts.debug_charges
```

## Tests

```bash
pytest
```

The PDF regression test uses sample CSVs under `backend/tests/fixtures/` and checks
that the generated PDF text contains key bill amounts.
