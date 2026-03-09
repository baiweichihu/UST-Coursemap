# UST-Coursemap
USTCourseMap: A tool that visualizes HKUST course prerequisites and integrates student reviews from USTSpace

## Step 1: WCQ Semester Snapshot

This project uses a per-semester snapshot policy.

- Crawl class schedule/quota data once for each semester code (`xxyy`).
- Reuse local snapshot file for the whole semester.
- Re-crawl only when needed with `--force-refresh`.

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
python scripts/crawl_wcq_snapshot.py 2530
```

Output file:

`data/snapshots/2530/raw_courses.json`

Force refresh:

```bash
python scripts/crawl_wcq_snapshot.py 2530 --force-refresh
```

## Step 2: USTSpace Review Snapshot + Merge

Milestone 2 uses Playwright for authenticated crawling and keeps per-semester cache files.

### Install Dependencies

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### Set Credentials (PowerShell)

```powershell
$env:USTSPACE_USERNAME="your_itsc"
$env:USTSPACE_PASSWORD="your_password"
```

### Run

```bash
python scripts/crawl_ustspace_snapshot.py 2530
```

Notes:

- Default crawl speed is conservative: `--request-interval-seconds 1.2`.
- Live progress is shown by default (count, percent, matched, ETA).
- You can slow down further with `--request-interval-seconds 2.0`.
- You can disable progress output with `--no-progress`.

Outputs:

- `data/snapshots/2530/ustspace_reviews.json`
- `data/snapshots/2530/merged_courses.json`
- `data/snapshots/2530/ustspace_storage_state.json`

Cache behavior:

- Reuses `ustspace_reviews.json` by default within same semester.
- Re-crawls only with `--force-refresh`.

Quick test run (small sample):

```bash
python scripts/crawl_ustspace_snapshot.py 2530 --limit 20 --force-refresh
```

Coverage analysis (no re-crawl needed):

```bash
python scripts/analyze_review_coverage.py 2530
# Optional: persist computed coverage metrics back into snapshot metadata
python scripts/analyze_review_coverage.py 2530 --write-back
```

Metric notes:

- `matched_ratio` uses all crawled courses as denominator.
- `matched_ratio_existing_pages` uses courses with detectable review pages as denominator.
- For the Milestone 2 acceptance phrase "matched with review data where review pages exist", the second denominator is the closer interpretation.

## Step 3: Milestone 3 Parser + Canonical Graph Payload

Build parser output and graph-ready payload from merged snapshot:

```bash
python scripts/build_m3_model.py 2530
```

Outputs:

- `data/snapshots/2530/canonical_courses.json`
- `data/snapshots/2530/graph_payload.json`

Model notes:

- No `AND/OR` logic nodes are included in graph nodes.
- `pre_req` edge style: single-direction, solid, double-head arrow metadata.
- `co_req` edge style: single-direction, solid, single-head arrow metadata.
- `exclusion` edge style: single-direction, dashed, single-head arrow metadata.
- Mutual exclusions are represented by two opposite-direction exclusion edges and marked with `is_mutual_exclusion=true`.
- Node payload includes `hover` fields (`course_code`, `title`, `special_tags`, 4-dimension reviews) and full `details` for click panels.

## Step 4: Streamlit Graph Prototype (M4)

Run interactive graph app:

```bash
streamlit run app.py
```

Implemented interactions:

- Course node is a rectangle (`box`) and initially shows course code on graph.
- Hover shows: course code, title, normalized special tags, and 4-dimension rating letters (`O/T/W/G`).
- Click a course node to focus on the full connected chain (both incoming and outgoing req/exclusion links).
- Click blank area (when event is emitted by the graph component) to clear current selection.
- Right panel shows full course details (excluding quota/enrol/avail/wait numbers in sections).
- Relations are always enabled (`pre_req` / `co_req` / `exclusion`) and no longer shown as a user filter.
- Search supports course code or title.
- Completed-course list is shown one course per row (sorted), with a red `-` button on the right to remove entries.
- `Add Selected As Completed` adds the currently selected node into completed courses.
- Current graph view can be exported as a standalone HTML file.
- Dense readability control is available with `Max nodes shown`.
- Sidebar shows snapshot file status only (manual refresh/rebuild buttons are removed from UI).

Edge style mapping in graph metadata:

- `pre_req`: double-line shaft emulation + directed arrow (`=>` semantics).
- `co_req`: directed solid line.
- `exclusion`: directed dashed line (mutual exclusion represented by two opposite directed dashed edges).

### Build Special Tag Dictionary

```bash
python scripts/build_tag_dictionary.py 2530
```

Outputs:

- `data/snapshots/2530/tag_dictionary.json`
- `data/snapshots/2530/tag_dictionary.md`

## Streamlit Deploy (M6)

### Local Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

### Streamlit Cloud

1. Push repository to GitHub.
2. Open Streamlit Community Cloud and create a new app from this repo.
3. Set `Main file path` to `app.py`.
4. Ensure Python dependencies come from `requirements.txt`.
5. (Optional) Add secrets only when online refresh actions are needed:
	- `USTSPACE_USERNAME`
	- `USTSPACE_PASSWORD`
	You can use `.streamlit/secrets.toml.example` as reference.
6. Deploy and verify:
	- At least one semester appears in selector.
	- Graph renders and node click updates detail panel.
	- Search and subject filter work.
	- Completed-course add/remove list works.
	- HTML export downloads successfully.

Operational notes:

- Crawler refresh/rebuild actions are not exposed in app UI.
- After changing `requirements.txt` or `.streamlit/config.toml`, trigger a redeploy from Streamlit Cloud app settings.
