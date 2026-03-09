import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import BrowserContext, Page, sync_playwright

from ust_coursemap.wcq_crawler import validate_semester

USTSPACE_LOGIN_URL = "https://ust.space/login"
USTSPACE_REVIEW_URL_TEMPLATE = "https://ust.space/review/{course_slug}"
USTSPACE_REVIEW_GET_URL_TEMPLATE = "https://ust.space/review/{course_slug}/get"


@dataclass
class ReviewRecord:
    course_code: str
    source_url: str
    review_count: Optional[int]
    overall: Optional[float]
    teaching: Optional[float]
    workload: Optional[float]
    grading: Optional[float]


def normalize_course_code(value: str) -> str:
    compact = re.sub(r"\s+", "", value.upper())
    m = re.fullmatch(r"([A-Z]{4})(\d{4}[A-Z]?)", compact)
    if not m:
        return value.strip().upper()
    return f"{m.group(1)} {m.group(2)}"


def snapshot_dir(project_root: Path, semester: str) -> Path:
    return project_root / "data" / "snapshots" / semester


def raw_courses_path(project_root: Path, semester: str) -> Path:
    return snapshot_dir(project_root, semester) / "raw_courses.json"


def ustspace_reviews_path(project_root: Path, semester: str) -> Path:
    return snapshot_dir(project_root, semester) / "ustspace_reviews.json"


def merged_courses_path(project_root: Path, semester: str) -> Path:
    return snapshot_dir(project_root, semester) / "merged_courses.json"


def storage_state_path(project_root: Path, semester: str) -> Path:
    return snapshot_dir(project_root, semester) / "ustspace_storage_state.json"


def _is_login_page(html: str) -> bool:
    return "You are required to login before accessing the page" in html


def _find_metric(text: str, label: str) -> Optional[float]:
    patterns = [
        rf'"{label}"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        rf"{label}\s*</[^>]+>\s*([0-9]+(?:\.[0-9]+)?)",
        rf"{label}\s*[:\-]\s*([0-9]+(?:\.[0-9]+)?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def _to_float_or_none(value: object) -> Optional[float]:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int_or_none(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if value.isdigit():
            return int(value)
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _extract_review_count(payload: dict) -> Optional[int]:
    if not isinstance(payload, dict):
        return None

    candidate_values: list[object] = []
    course = payload.get("course")
    if isinstance(course, dict):
        for key in [
            "review_count",
            "reviews_count",
            "rating_count",
            "ratings_count",
            "total_reviews",
            "num_reviews",
            "reviewCount",
            "reviewsCount",
        ]:
            candidate_values.append(course.get(key))

    for key in [
        "review_count",
        "reviews_count",
        "rating_count",
        "ratings_count",
        "total_reviews",
        "num_reviews",
        "reviewCount",
        "reviewsCount",
    ]:
        candidate_values.append(payload.get(key))

    for value in candidate_values:
        parsed = _to_int_or_none(value)
        if parsed is not None and parsed >= 0:
            return parsed

    reviews_obj = payload.get("reviews")
    if isinstance(reviews_obj, list):
        return len(reviews_obj)
    return None


def parse_review_metrics_from_payload(payload: dict) -> dict[str, Optional[float]]:
    course = payload.get("course") if isinstance(payload, dict) else None
    if not isinstance(course, dict):
        return {
            "overall": None,
            "teaching": None,
            "workload": None,
            "grading": None,
        }

    content = _to_float_or_none(course.get("rating_content"))
    teaching = _to_float_or_none(course.get("rating_teaching"))
    grading = _to_float_or_none(course.get("rating_grading"))
    workload = _to_float_or_none(course.get("rating_workload"))

    parts = [v for v in [content, teaching, grading, workload] if v is not None]
    overall = (sum(parts) / len(parts)) if parts else None

    return {
        "overall": overall,
        "teaching": teaching,
        "workload": workload,
        "grading": grading,
    }


def has_review_page_payload(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    course = payload.get("course")
    return isinstance(course, dict)


def parse_review_metrics(html: str) -> dict[str, Optional[float]]:
    return {
        "overall": _find_metric(html, "overall"),
        "teaching": _find_metric(html, "teaching"),
        "workload": _find_metric(html, "workload"),
        "grading": _find_metric(html, "grading"),
    }


def _do_login(page: Page, username: str, password: str) -> None:
    page.goto(USTSPACE_LOGIN_URL, wait_until="domcontentloaded")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-btn")
    page.wait_for_timeout(1500)


def _ensure_logged_in(
    context: BrowserContext,
    *,
    username: Optional[str],
    password: Optional[str],
    state_file: Path,
) -> None:
    page = context.new_page()
    page.goto("https://ust.space/review", wait_until="domcontentloaded")
    html = page.content()

    if not _is_login_page(html):
        return

    if not username or not password:
        raise RuntimeError(
            "USTSpace login required. Set USTSPACE_USERNAME and USTSPACE_PASSWORD, "
            "or provide a valid storage state file."
        )

    _do_login(page, username, password)
    page.goto("https://ust.space/review", wait_until="domcontentloaded")
    html = page.content()
    if _is_login_page(html):
        raise RuntimeError("USTSpace login failed. Please verify credentials.")

    state_file.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(state_file))


def load_raw_course_codes(project_root: Path, semester: str) -> list[str]:
    raw_file = raw_courses_path(project_root, semester)
    if not raw_file.exists():
        raise RuntimeError(
            f"Raw courses snapshot not found: {raw_file}. "
            "Run milestone 1 crawler first."
        )

    payload = json.loads(raw_file.read_text(encoding="utf-8"))
    codes = []
    for course in payload.get("courses", []):
        code = normalize_course_code(str(course.get("course_code", "")))
        if code and code not in codes:
            codes.append(code)
    return codes


def crawl_ustspace_reviews(
    semester: str,
    *,
    project_root: Path,
    force_refresh: bool = False,
    request_interval_seconds: float = 1.2,
    limit: Optional[int] = None,
    show_progress: bool = True,
) -> tuple[Path, bool]:
    semester = validate_semester(semester)
    out_file = ustspace_reviews_path(project_root, semester)
    if out_file.exists() and not force_refresh:
        return out_file, True

    course_codes = load_raw_course_codes(project_root, semester)
    if limit is not None:
        course_codes = course_codes[: max(limit, 0)]

    username = os.getenv("USTSPACE_USERNAME")
    password = os.getenv("USTSPACE_PASSWORD")
    state_file = storage_state_path(project_root, semester)

    reviews: list[ReviewRecord] = []
    matched = 0
    review_page_exists_count = 0

    def print_progress(index: int) -> None:
        if not show_progress:
            return
        total = len(course_codes)
        pct = (index / total * 100.0) if total else 100.0
        elapsed = time.time() - start_ts
        avg = (elapsed / index) if index > 0 else 0.0
        remain = max(total - index, 0)
        eta = avg * remain
        bar_width = 24
        fill = int((pct / 100.0) * bar_width)
        bar = ("#" * fill) + ("-" * (bar_width - fill))
        line = (
            f"\rProgress [{bar}] {index}/{total} ({pct:5.1f}%) "
            f"matched={matched} elapsed={elapsed:6.1f}s eta={eta:6.1f}s"
        )
        sys.stdout.write(line)
        sys.stdout.flush()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context_kwargs = {}
        if state_file.exists():
            context_kwargs["storage_state"] = str(state_file)

        context = browser.new_context(**context_kwargs)
        _ensure_logged_in(context, username=username, password=password, state_file=state_file)
        start_ts = time.time()
        print_progress(0)

        for i, course_code in enumerate(course_codes):
            if i > 0 and request_interval_seconds > 0:
                time.sleep(request_interval_seconds)

            slug = course_code.replace(" ", "")
            url = USTSPACE_REVIEW_URL_TEMPLATE.format(course_slug=slug)
            get_url = USTSPACE_REVIEW_GET_URL_TEMPLATE.format(course_slug=slug)

            response = context.request.get(
                get_url,
                params={
                    "single": "false",
                    "composer": "false",
                    "preferences[sort]": "0",
                    "preferences[filterInstructor]": "0",
                    "preferences[filterSemester]": "0",
                    "preferences[filterRating]": "0",
                },
            )
            payload = {}
            if response.ok:
                try:
                    payload = response.json()
                except Exception:
                    payload = {}
            else:
                body = response.text()
                if _is_login_page(body):
                    raise RuntimeError(
                        "Session expired while crawling USTSpace. "
                        "Please re-run with valid credentials."
                    )

            metrics = parse_review_metrics_from_payload(payload)
            review_count = _extract_review_count(payload)
            if has_review_page_payload(payload):
                review_page_exists_count += 1
            has_any_metric = any(v is not None for v in metrics.values())
            if has_any_metric:
                matched += 1

            reviews.append(
                ReviewRecord(
                    course_code=course_code,
                    source_url=url,
                    review_count=review_count,
                    overall=metrics["overall"],
                    teaching=metrics["teaching"],
                    workload=metrics["workload"],
                    grading=metrics["grading"],
                )
            )
            print_progress(i + 1)

        if show_progress:
            sys.stdout.write("\n")
            sys.stdout.flush()

        context.storage_state(path=str(state_file))
        context.close()
        browser.close()

    payload = {
        "semester": semester,
        "generated_at_epoch": int(time.time()),
        "course_count": len(course_codes),
        "review_page_exists_count": review_page_exists_count,
        "matched_count": matched,
        "matched_ratio": (matched / len(course_codes)) if course_codes else 0.0,
        "matched_ratio_existing_pages": (
            (matched / review_page_exists_count) if review_page_exists_count else 0.0
        ),
        "reviews": [asdict(r) for r in reviews],
    }

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return out_file, False


def merge_raw_and_reviews(semester: str, *, project_root: Path) -> Path:
    semester = validate_semester(semester)
    raw_file = raw_courses_path(project_root, semester)
    review_file = ustspace_reviews_path(project_root, semester)
    out_file = merged_courses_path(project_root, semester)

    if not raw_file.exists():
        raise RuntimeError(f"Raw snapshot missing: {raw_file}")
    if not review_file.exists():
        raise RuntimeError(f"USTSpace snapshot missing: {review_file}")

    raw_payload = json.loads(raw_file.read_text(encoding="utf-8"))
    review_payload = json.loads(review_file.read_text(encoding="utf-8"))

    review_map: dict[str, dict[str, Optional[float] | Optional[int]]] = {}
    for item in review_payload.get("reviews", []):
        code = normalize_course_code(str(item.get("course_code", "")))
        review_map[code] = {
            "review_count": item.get("review_count"),
            "overall": item.get("overall"),
            "teaching": item.get("teaching"),
            "workload": item.get("workload"),
            "grading": item.get("grading"),
        }

    merged_courses = []
    for course in raw_payload.get("courses", []):
        code = normalize_course_code(str(course.get("course_code", "")))
        review = review_map.get(
            code,
            {
                "review_count": None,
                "overall": None,
                "teaching": None,
                "workload": None,
                "grading": None,
            },
        )
        merged_courses.append({**course, "reviews": review})

    merged_payload = {
        "semester": semester,
        "generated_at_epoch": int(time.time()),
        "course_count": len(merged_courses),
        "courses": merged_courses,
    }

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(merged_payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return out_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or reuse USTSpace review snapshot and merge output.")
    parser.add_argument("semester", help="Semester code in xxyy format, e.g. 2530")
    parser.add_argument("--force-refresh", action="store_true", help="Ignore cache and re-crawl USTSpace")
    parser.add_argument(
        "--request-interval-seconds",
        type=float,
        default=1.2,
        help="Delay between review-page requests",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of courses for test runs")
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable live progress output",
    )

    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    review_file, from_cache = crawl_ustspace_reviews(
        args.semester,
        project_root=root,
        force_refresh=args.force_refresh,
        request_interval_seconds=args.request_interval_seconds,
        limit=args.limit,
        show_progress=not args.no_progress,
    )
    merged_file = merge_raw_and_reviews(args.semester, project_root=root)

    status = "reused" if from_cache else "created"
    print(f"USTSpace snapshot {status}: {review_file}")
    print(f"Merged snapshot created: {merged_file}")
    return 0
