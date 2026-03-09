import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

SEMESTER_RE = re.compile(r"^\d{4}$")
SUBJECT_RE = re.compile(r"^([A-Z]{4})\s*(\d{4}[A-Z]?)\s*-\s*(.*?)\s*\((\d+)\s+units\)$")
DEFAULT_TIMEOUT_SECONDS = 30


@dataclass
class SectionRecord:
    section: str
    date_time: str
    room: str
    instructor: str
    ta_ia_gta: str
    quota: Optional[int]
    enrol: Optional[int]
    avail: Optional[int]
    wait: Optional[int]
    remarks: str


@dataclass
class CourseRecord:
    course_code: str
    title: str
    credits: Optional[int]
    pre_req_text: str
    co_req_text: str
    exclusion_text: str
    attributes_text: str
    description: str
    cross_campus_course_equivalence: str
    alternate_codes: str
    class_quota_total: Optional[int]
    class_enrol_total: Optional[int]
    class_avail_total: Optional[int]
    class_wait_total: Optional[int]
    sections: list[SectionRecord]


def validate_semester(semester: str) -> str:
    if not SEMESTER_RE.match(semester):
        raise ValueError("Semester must be in xxyy format, e.g. 2530.")
    return semester


def build_semester_url(semester: str) -> str:
    validate_semester(semester)
    return f"https://w5.ab.ust.hk/wcq/cgi-bin/{semester}/"


def _get_text(node: Optional[Tag]) -> str:
    if node is None:
        return ""
    return " ".join(node.stripped_strings)


def _attr_value_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(str(x) for x in value)
    return str(value)


def _parse_subject_header(text: str) -> tuple[str, str, Optional[int]]:
    m = SUBJECT_RE.match(" ".join(text.split()))
    if not m:
        normalized = " ".join(text.split())
        return "", normalized, None

    subject, number, title, credits = m.groups()
    return f"{subject} {number}", title.strip(), int(credits)


def _course_code_from_anchor(course_node: Tag) -> str:
    anchor = course_node.select_one("div.courseanchor a")
    if anchor is None:
        return ""
    name = _attr_value_to_text(anchor.get("name")).strip()
    m = re.fullmatch(r"([A-Z]{4})(\d{4}[A-Z]?)", name)
    if not m:
        return ""
    return f"{m.group(1)} {m.group(2)}"


def _to_int(value: str) -> Optional[int]:
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    if cleaned == "":
        return None
    if not re.fullmatch(r"-?\d+", cleaned):
        return None
    return int(cleaned)


def _join_names(cell: Optional[Tag]) -> str:
    if cell is None:
        return ""
    names = [" ".join(x.split()) for x in cell.stripped_strings]
    return "; ".join([name for name in names if name])


def _extract_course_attrs(course_node: Tag) -> dict[str, str]:
    attrs = {
        "PRE-REQUISITE": "",
        "CO-REQUISITE": "",
        "EXCLUSION": "",
        "ATTRIBUTES": "",
        "DESCRIPTION": "",
        "CROSS CAMPUS COURSE EQUIVALENCE": "",
        "ALTERNATE CODE(S)": "",
    }

    detail = course_node.select_one("div.courseattr div.popupdetail table")
    if detail is None:
        return attrs

    for row in detail.select("tr"):
        th = row.find("th")
        td = row.find("td")
        if th is None or td is None:
            continue
        key = _get_text(th).upper().replace("\n", " ").strip()
        key = " ".join(key.split())
        if key.startswith("ATTRIBUTES"):
            attrs["ATTRIBUTES"] = _get_text(td)
            continue
        if key in attrs:
            attrs[key] = _get_text(td)
    return attrs


def _parse_section_table(course_node: Tag) -> list[SectionRecord]:
    table = course_node.find("table", class_="sections")
    if table is None:
        return []

    sections: list[SectionRecord] = []
    for row in table.select("tr.mainRow"):
        cells = row.find_all("td")
        if len(cells) < 10:
            continue

        sections.append(
            SectionRecord(
                section=_get_text(cells[0]),
                date_time=_get_text(cells[1]),
                room=_get_text(cells[2]),
                instructor=_join_names(cells[3]),
                ta_ia_gta=_join_names(cells[4]),
                quota=_to_int(_get_text(cells[5])),
                enrol=_to_int(_get_text(cells[6])),
                avail=_to_int(_get_text(cells[7])),
                wait=_to_int(_get_text(cells[8])),
                remarks=_get_text(cells[9]),
            )
        )
    return sections


def _sum_optional(values: list[Optional[int]]) -> Optional[int]:
    numeric = [v for v in values if v is not None]
    if not numeric:
        return None
    return sum(numeric)


def parse_courses(html: str) -> list[CourseRecord]:
    soup = BeautifulSoup(html, "html.parser")
    course_nodes = soup.select("div#classes > div.course")
    parsed: list[CourseRecord] = []

    for node in course_nodes:
        subject_node = node.select_one("div.courseinfo div.subject")
        code, title, credits = _parse_subject_header(_get_text(subject_node))
        if not code:
            code = _course_code_from_anchor(node)
        attrs = _extract_course_attrs(node)
        sections = _parse_section_table(node)

        parsed.append(
            CourseRecord(
                course_code=code,
                title=title,
                credits=credits,
                pre_req_text=attrs["PRE-REQUISITE"],
                co_req_text=attrs["CO-REQUISITE"],
                exclusion_text=attrs["EXCLUSION"],
                attributes_text=attrs["ATTRIBUTES"],
                description=attrs["DESCRIPTION"],
                cross_campus_course_equivalence=attrs["CROSS CAMPUS COURSE EQUIVALENCE"],
                alternate_codes=attrs["ALTERNATE CODE(S)"],
                class_quota_total=_sum_optional([s.quota for s in sections]),
                class_enrol_total=_sum_optional([s.enrol for s in sections]),
                class_avail_total=_sum_optional([s.avail for s in sections]),
                class_wait_total=_sum_optional([s.wait for s in sections]),
                sections=sections,
            )
        )

    return parsed


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "USTCourseMap/0.1 (+https://github.com)",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def _fetch_url_with_retry(
    session: requests.Session,
    url: str,
    *,
    retries: int,
    delay_seconds: float,
    timeout_seconds: int,
) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, timeout=timeout_seconds)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay_seconds)
            continue

    if last_error is None:
        raise RuntimeError("Unknown request failure")
    raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error


def _extract_subject_urls(index_html: str, semester: str) -> list[str]:
    base = build_semester_url(semester)
    soup = BeautifulSoup(index_html, "html.parser")
    links = soup.select("#subjectItems a[href]")
    seen: set[str] = set()
    urls: list[str] = []

    for link in links:
        href = _attr_value_to_text(link.get("href")).strip()
        if f"/{semester}/subject/" not in href:
            continue
        full_url = urljoin(base, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        urls.append(full_url)

    return urls


def fetch_semester_html(
    semester: str,
    *,
    retries: int = 3,
    delay_seconds: float = 1.0,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    url = build_semester_url(semester)
    session = _new_session()
    return _fetch_url_with_retry(
        session,
        url,
        retries=retries,
        delay_seconds=delay_seconds,
        timeout_seconds=timeout_seconds,
    )


def snapshot_path(project_root: Path, semester: str) -> Path:
    return project_root / "data" / "snapshots" / semester / "raw_courses.json"


def build_snapshot_payload(semester: str, url: str, courses: list[CourseRecord]) -> dict:
    return {
        "semester": semester,
        "source": url,
        "generated_at_epoch": int(time.time()),
        "course_count": len(courses),
        "courses": [
            {
                **asdict(course),
                "sections": [asdict(section) for section in course.sections],
            }
            for course in courses
        ],
    }


def crawl_semester(
    semester: str,
    *,
    project_root: Path,
    force_refresh: bool = False,
    retries: int = 3,
    delay_seconds: float = 1.0,
    request_interval_seconds: float = 0.3,
) -> tuple[Path, bool]:
    semester = validate_semester(semester)
    out_file = snapshot_path(project_root, semester)

    if out_file.exists() and not force_refresh:
        return out_file, True

    index_url = build_semester_url(semester)
    session = _new_session()
    index_html = _fetch_url_with_retry(
        session,
        index_url,
        retries=retries,
        delay_seconds=delay_seconds,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )

    subject_urls = _extract_subject_urls(index_html, semester)
    if not subject_urls:
        raise RuntimeError(f"No subject URLs found on index page: {index_url}")

    all_courses: list[CourseRecord] = []
    seen_codes: set[str] = set()
    for i, subject_url in enumerate(subject_urls):
        if i > 0 and request_interval_seconds > 0:
            time.sleep(request_interval_seconds)
        html = _fetch_url_with_retry(
            session,
            subject_url,
            retries=retries,
            delay_seconds=delay_seconds,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        )
        for course in parse_courses(html):
            if course.course_code and course.course_code in seen_codes:
                continue
            if course.course_code:
                seen_codes.add(course.course_code)
            all_courses.append(course)

    payload = build_snapshot_payload(semester, index_url, all_courses)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return out_file, False


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or reuse WCQ semester snapshot.")
    parser.add_argument("semester", help="Semester code in xxyy format, e.g. 2530")
    parser.add_argument("--force-refresh", action="store_true", help="Ignore cache and re-crawl")
    parser.add_argument("--retries", type=int, default=3, help="Retry count for network requests")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=1.0,
        help="Delay between retry attempts",
    )
    parser.add_argument(
        "--request-interval-seconds",
        type=float,
        default=0.3,
        help="Delay between subject-page requests",
    )

    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    out_file, from_cache = crawl_semester(
        args.semester,
        project_root=root,
        force_refresh=args.force_refresh,
        retries=args.retries,
        delay_seconds=args.delay_seconds,
        request_interval_seconds=args.request_interval_seconds,
    )

    status = "reused" if from_cache else "created"
    print(f"Snapshot {status}: {out_file}")
    return 0
