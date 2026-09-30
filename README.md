# Swachh AI

A FastAPI + HTML/CSS/JavaScript app for recurring visual cleanliness inspections using Gemini Flash. Create a location with fixed clean reference images, upload workforce photos, and get an evidence-based report with an estimated cleanliness percentage, objects/issues, actions, limitations, and per-photo comparisons.

## Run locally

Python 3.11+ recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set GEMINI_API_KEY in .env (or enter it through the UI)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. API docs: http://127.0.0.1:8000/docs.

The default model is `gemini-3.8-flash`; set `GEMINI_MODEL` to a Gemini Flash model available to your account if needed, then restart. The app uses Gemini's `generateContent` REST endpoint with inline images and JSON-schema output. No API key is bundled. A UI-supplied key lives only in page memory and is not saved to local storage or the database. `.env` is ignored by Git.

## Workflow

1. Create a named location. Add 1–6 clean reference photos with distinct viewpoints covering the cleaning area.
2. References are immutable: future inspections reuse those same saved images. Create a new location when the clean standard changes.
3. Upload 1–6 current photos, ideally matching each reference viewpoint. Run the inspection.
4. Review the total score, individual matched photos, objects on the ground, approximate counts, severity, visual evidence, and suggested actions. Click photos to enlarge. Download the report as JSON or reopen it in history.

Photos must be non-animated JPEG, PNG, or WebP, ≤8 MB each, ≥128 pixels per side, and ≤25 megapixels. The request limit is 50 MB. The server checks actual image content, corrects EXIF orientation, strips metadata and normalizes to JPEG with a 1600-pixel maximum side. Keep details large enough to see after resizing.

## What the percentage means

This is a **visual cleanliness index relative to the clean reference**, not a literal measurement of the percentage of dirt removed. A dirty before-photo would be required to estimate cleaning improvement. It cannot assess microbial cleanliness or prove when cleaning happened.

The model returns three 0–100 component scores and evidence for each current image. The server, not the model, computes:

`cleanliness = 0.50 × litter-free + 0.35 × surface cleanliness + 0.15 × orderly surroundings`

Anchors: 100 = clean reference standard, 90 = minor localized defects, 75 = several localized defects, 50 = widespread moderate issues, 25 = substantial accumulation, 0 = pervasive severe issues. The full versioned prompt is `app/prompt.py`; weights and validation are in `app/schemas.py`.

The app withholds a photo's score if there is no reliable reference match, model confidence <60%, reference area visibility <50%, or a missing component. For multiple photos matching the same reference, the lowest eligible score is used. Every reference view must be represented, and every submitted photo must be assessable to receive an overall score. The overall score is the equally weighted mean across reference views, not a physical area-weighted measurement. Choose similarly sized reference areas; overlapping views can otherwise bias the index.

Labels: ≥90 clean, ≥75 mostly clean, <75 needs cleaning; insufficient evidence means needs review. Model confidence is self-reported and uncalibrated. `clean_visible_area_percent` is a separate rough estimate of defect-free visible ground area. All scores remain estimates: test on a labeled collection of your own site photos and adjust rubric/thresholds before using them for operational decisions. No prompt can guarantee perfect vision judgments.

## Storage and deployment scope

SQLite stores locations and inspection reports in `data/swachh.db`; normalized images are in `data/media/`. Failed Gemini requests do not save inspections. Restarting preserves history. `DATA_DIR` can override the storage directory. References and current photos are sent to Google Gemini on each comparison; fixed references are stored locally, not in an expiring provider file cache.

This is a local single-workspace prototype with no authentication. Keep it bound to localhost. Before sharing remotely, add authentication/authorization, HTTPS, per-user quotas, retention/deletion controls, and a production request-size limit at the proxy. All local users of the app can access all photos and reports. There is no scheduled upload, workforce identity verification, or multi-tenant isolation. Two concurrent Gemini calls per process are allowed; deployment-wide limits require a shared queue.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use synthetic images and mocked Gemini responses; they do not spend API credits or validate real model accuracy. Coverage includes reference persistence, upload validation, weighted scoring, duplicate-view handling, incomplete coverage, key non-persistence, API error handling, and structured-response parsing.

## API

- `GET /api/config` — model and server key availability (never the key)
- `GET /api/locations` — saved locations and references
- `POST /api/locations` — multipart `name`, repeated `images`
- `POST /api/locations/{id}/inspections` — multipart repeated `images`, optional `api_key`
- `GET /api/locations/{id}/inspections` — history
- `GET /api/inspections/{id}` — full report
- `GET /media/{filename}` — stored image

Provider documentation: [image understanding](https://ai.google.dev/gemini-api/docs/image-understanding), [structured outputs](https://ai.google.dev/gemini-api/docs/structured-output), [generateContent API](https://ai.google.dev/api/generate-content).
