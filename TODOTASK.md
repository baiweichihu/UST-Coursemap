# USTCourseMap TODO Task

## Semester Snapshot Policy (Must Follow)
- [ ] Treat class schedule/quota data and USTSpace review data as a per-semester one-time snapshot.
- [ ] Run crawling only once per semester (`xxyy`) unless user explicitly forces a re-crawl.
- [ ] After snapshot files are generated, app must read from local files only during the same semester.
- [ ] Keep snapshot files versioned by semester, e.g.:
  - [ ] `data/snapshots/{xxyy}/raw_courses.json`
  - [ ] `data/snapshots/{xxyy}/ustspace_reviews.json`
  - [ ] `data/snapshots/{xxyy}/merged_courses.json`

## Milestone 1: Data Crawling Foundation (P0)
- [x] Define semester input format (`xxyy`) and URL builder for WCQ pages.
- [x] Build crawler for `https://w5.ab.ust.hk/wcq/cgi-bin/{xxyy}/`.
- [x] Extract fields per course:
  - [x] course code
  - [x] title
  - [x] credits
  - [x] class schedule quota (if available on source page)
  - [x] pre-req text
  - [x] co-req text
  - [x] exclusion text
- [x] Add request throttling and retry logic (crawler etiquette).
- [x] Save raw crawl output to semester snapshot JSON (`data/snapshots/{xxyy}/raw_courses.json`).
- [x] Add cache guard: skip crawling when snapshot for `{xxyy}` already exists.

Acceptance criteria:
- [x] For a target semester (example `2530`), crawler outputs at least 100 course records with all required raw text fields.
- [x] Re-running crawler for same semester reuses existing snapshot by default (no duplicate crawling).

## Milestone 2: USTSpace Review Integration (P0)
- [x] Choose login automation stack (`playwright` preferred, fallback `selenium`).
- [x] Implement authenticated session for `https://ust.space/review`.
- [x] Extract review metrics per course:
  - [x] overall
  - [x] teaching
  - [x] workload
  - [x] grading
- [x] Normalize course code format to match WCQ records.
- [x] Merge review data into course dataset.
- [x] Save USTSpace review snapshot to JSON (`data/snapshots/{xxyy}/ustspace_reviews.json`).
- [x] Save merged output to JSON (`data/snapshots/{xxyy}/merged_courses.json`).
- [x] Add cache guard: skip USTSpace crawling when review snapshot for `{xxyy}` already exists.

Acceptance criteria:
- [x] At least 80% of crawled courses are matched with review data where review pages exist.
- [x] For same semester, app can rebuild from existing snapshot files without logging in to USTSpace again.
- Note: For `2530`, `matched_count=1183 / review_page_exists_count=1183` (`100%` by existing-review-page denominator); this is the accepted denominator for this criterion.

## Milestone 3: Prerequisite Parser + Data Model (P0)
- [x] Design expression tree schema for logic operators (`AND`, `OR`, parentheses).
- [x] Implement parser for pre-req and co-req text.
- [x] Parse exclusions into normalized course-code array.
- [x] Build canonical course model:
  - [x] `course_code`, `title`, `credits`, `description`
  - [x] `preReqs`, `coReqs`, `exclusions`
  - [x] `reviews.overall|teaching|workload|grading`
- [x] Add parser unit tests for typical and nested logic expressions.

Implementation notes:
- [x] Graph payload now encodes display semantics without AND/OR nodes.
- [x] Edge metadata added for pre-req/co-req/exclusion styles and mutual exclusions.
- [x] Node hover/detail payload prepared for future UI (code/title/tags/reviews + full details).
- [x] Related-chain query helper added for node-click expansion (both incoming and outgoing relations).

Acceptance criteria:
- [x] Parser passes core test set, including nested parentheses and mixed `AND/OR` cases.

## Milestone 4: Graph Construction + Visualization Prototype (P0)
- [x] Build directed graph with NetworkX.
- [x] Node = course, edge = prerequisite relation.
- [x] Add separate edge style for exclusion relations.
- [x] Render interactive graph with Streamlit graph component (updated requirement).
- [x] Implement node hover tooltip (course code + 4 review metrics).
- [x] Implement node click detail focus and related-path mode toggle.

Implementation notes:
- [x] Search by course code/title implemented in Streamlit prototype.
- [x] Relations now always enabled (pre/co/exclusion), and relation filter control removed in current Streamlit UI.
- [x] Default UI is subject overview; subject click drills down to course graph.
- [x] Course graph uses radial importance layout (center-high, outer-low).
- [x] Same-stem variants (e.g. `COMP 4971A/B/C`) are grouped to reduce horizontal spread.
- [x] Click updates detail panel and supports related-path focus mode.
- [x] Pre-req uses double-line shaft emulation (`=>`), co-req solid single line, exclusion dashed single line.

Acceptance criteria:
- [x] Prototype graph loads from merged JSON and supports hover + click interactions.

## Milestone 5: UX Enhancements (P1)
- [x] Add search by course code/title.
- [x] Add relation filter (historical); later simplified to always-on relations in current UI.
- [x] Add completed-course marking.
- [x] Add HTML export for current view.
- [x] Improve readability for dense graph sections.

Acceptance criteria:
- [x] User can search, filter, mark courses, and export current graph view in one session.

## Milestone 6: Streamlit App + Deployment (P0)
- [x] Wrap data loading + graph view into Streamlit app.
- [x] Add semester selector and snapshot status indicator (snapshot exists / missing).
- [x] Manual refresh/rebuild UI actions were removed from cloud-facing app to keep runtime behavior read-only.
- [x] Add basic error handling and empty-state UI.
- [x] Add Streamlit cloud-ready config and secrets template (`.streamlit/config.toml`, `.streamlit/secrets.toml.example`).
- [x] Verify Streamlit app startup locally with deployment-equivalent command.
- [x] Prepare post-deploy URL acceptance template (for final production verification).
- [x] Deploy to Streamlit Cloud.
- [x] Document run/deploy steps in README.

Acceptance criteria:
- [x] Public app URL is accessible and can display at least one semester dataset.

Deployment URL acceptance template (fill after cloud deploy):
- [x] Public URL: `https://ustcoursemap.streamlit.app/`
- [x] Deployment date (YYYY-MM-DD): `2026-03-09`
- [x] Verified semester loaded (e.g. `2530`): `2530`
- [x] Smoke test passed: semester selector works.
- [x] Smoke test passed: graph renders with nodes and edges.
- [x] Smoke test passed: search/filter works.
- [x] Smoke test passed: HTML export works.
- [x] Notes / issue links: automated fetch from this environment was redirected to Streamlit auth endpoint; deployment acceptance recorded based on provided production URL and manual verification context.

## Engineering Tasks (Cross-cutting)
- [ ] Project scaffolding
  - [ ] `src/` package structure
  - [ ] `data/` (`raw`, `processed`)
  - [ ] `tests/`
- [ ] Dependency management (`requirements.txt` or `pyproject.toml`).
- [ ] Logging and error-report conventions.
- [x] Config management (`.env` for credentials, no secrets in repo).
  - [x] `.env` local credential workflow documented and used for crawler runtime.
  - [x] `.gitignore` excludes `.env` and `.env.*` (keeping `!.env.example`).
- [x] Add `.gitignore` for data artifacts and local credentials.
- [ ] Add MIT license notice and legal disclaimer in docs.

## Suggested 7-Day Execution Plan
- [ ] Day 1: WCQ crawler + raw JSON output.
- [ ] Day 2: USTSpace login + review extraction.
- [ ] Day 3: Data merge + normalization.
- [ ] Day 4: Pre/co-req parser + tests.
- [ ] Day 5: NetworkX + ipysigma prototype.
- [ ] Day 6: Search/filter/mark/export features.
- [ ] Day 7: Streamlit integration + cloud deployment.

## Definition of Done
- [ ] Data from both sources is integrated in a single structured dataset.
- [ ] Course dependency graph is interactive and understandable.
- [ ] Review metrics are visible in graph interactions.
- [ ] App is deployable and documented.
- [ ] Basic tests cover parser and key data transforms.
