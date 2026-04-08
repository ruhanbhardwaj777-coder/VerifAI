# Fact Checker AI(VerifAI)

An AI-powered full-stack fact-checking web app and Progressive Web App (PWA).

## What's included

```
factchecker/
├── app.py              ← Flask backend + SQLite + AI logic
├── facts.db            ← Auto-generated SQLite database (14 seed claims)
├── start.sh            ← One-command startup script
├── requirements.txt    ← Python dependencies
└── static/
    ├── index.html      ← Full SPA frontend (all 4 pages)
    ├── manifest.json   ← PWA manifest (installable on mobile)
    └── sw.js           ← Service worker (offline support)
```

## Tech stack

- **Backend**: Python + Flask, SQLite
- **Frontend**: Vanilla HTML/CSS/JS — no build step needed
- **Mobile**: Progressive Web App (PWA) — installable on iOS and Android
- **AI logic**: Rule-based heuristic analysis + fuzzy keyword matching

## Quick start

```bash
# Install dependencies
pip install flask

# Start the server
cd factchecker
python app.py
```

Then open http://localhost:5050 in your browser.

## Installing as a mobile app (PWA)

**iOS (Safari):**
1. Open http://localhost:5050 in Safari
2. Tap the Share button → "Add to Home Screen"

**Android (Chrome):**
1. Open the URL in Chrome
2. Tap the menu → "Add to Home screen" or look for the install banner

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/check` | Submit a claim for fact-checking |
| GET | `/api/trending` | Top 12 most-checked claims |
| GET | `/api/history` | Last 50 claims checked |
| GET | `/api/stats` | Summary stats (totals by verdict/category) |

### POST /api/check

Request:
```json
{ "claim": "The Earth is flat" }
```

Response:
```json
{
  "claim_text": "The Earth is flat",
  "verdict": "false",
  "explanation": "The Earth is an oblate spheroid...",
  "confidence": 100,
  "category": "science",
  "sources": ["NASA", "ESA", "NOAA"],
  "from_db": true,
  "created_at": "2024-01-15T12:34:56"
}
```

## Verdict types

| Verdict | Meaning |
|---------|---------|
| `true` | Supported by credible evidence |
| `false` | Contradicted by credible evidence |
| `misleading` | Partially true but missing important context |
| `insufficient evidence` | Cannot be confirmed or denied with current data |
| `unverifiable` | Opinion, prediction, or not a factual claim |

## How the AI logic works

1. **Database lookup**: Checks for exact hash match first, then fuzzy keyword overlap (>50% match triggers a result).
2. **Heuristic analysis** (for new claims):
   - Opinion markers → `unverifiable`
   - Future predictions → `unverifiable`
   - Conspiracy language patterns → `false` (85% confidence)
   - Statistical claims → `insufficient evidence` with source recommendations
   - Everything else → `insufficient evidence` with general guidance
3. **All results stored** in SQLite so repeat checks are instant.

## Extending the database

Add more verified claims directly in `app.py` in the `seed_data` list, or POST to `/api/check` — every new claim gets stored automatically.
