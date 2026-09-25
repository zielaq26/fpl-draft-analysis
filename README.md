# FPL Draft H2H — Streamlit

This is the first migration of the Excel tracker to Streamlit.

## What it currently does

- Defaults to FPL Draft league **48609**.
- Pulls league/manager information from the Draft FPL API.
- Pulls each manager's gameweek score.
- Recreates the Excel workbook's main calculations:
  - Gameweek scores
  - League-average score
  - Relative 0–4 points (the workbook's "3 points table" concept)
  - Expected H2H points
  - Actual H2H points when the Draft API exposes the schedule in the league details response
  - Delta points
  - 5-GW periods
  - Current league table
  - H2H matrix
- Provides simple cumulative charts.
- Keeps the API layer separate enough that additional Draft data can be added later (players, transactions, draft choices, ownership, etc.).

## Run locally

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

## Important API note

The FPL Draft API is an undocumented API used by the Draft website. Community documentation identifies endpoints such as `/api/league/{league_id}/details`, `/api/draft/{league_id}/choices`, and `/api/entry/{entry_id}/event/{gw}`. The API can change without notice.

The app therefore uses defensive parsing rather than assuming one exact JSON structure for all responses.

## Next step

Once the basic migration is confirmed, the app can be refactored into:

- `fpl_api.py` — API access/caching
- `calculations.py` — league mathematics
- `app.py` — Streamlit UI

That will make it easier to add the new analytics later without turning the UI into a large single file.
