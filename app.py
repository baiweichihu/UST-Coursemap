import json
import html
import math
import re
import sys
import time
from collections import Counter
from urllib.parse import quote
from pathlib import Path
from typing import Any, Optional

import networkx as nx
import streamlit as st
from streamlit_agraph import Config, Edge, Node, agraph

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _rating_letter(value: Optional[float]) -> str:
    if value is None or value <= 0:
        return "N/A"
    if value >= 4.85:
        return "A+"
    if value >= 4.5:
        return "A"
    if value >= 4.15:
        return "A-"
    if value >= 3.85:
        return "B+"
    if value >= 3.5:
        return "B"
    if value >= 3.15:
        return "B-"
    if value >= 2.85:
        return "C+"
    if value >= 2.5:
        return "C"
    if value >= 2.15:
        return "C-"
    if value >= 1.85:
        return "D+"
    if value >= 1.5:
        return "D"
    if value >= 1.15:
        return "D-"
    return "E"


def _rating_quadletters(reviews: dict[str, Optional[float]]) -> str:
    overall = _rating_letter(reviews.get("overall"))
    teaching = _rating_letter(reviews.get("teaching"))
    workload = _rating_letter(reviews.get("workload"))
    grading = _rating_letter(reviews.get("grading"))
    return f"{overall}/{teaching}/{workload}/{grading}"


def _normalize_reviews_for_display(reviews: dict[str, Optional[float]]) -> dict[str, Optional[float]]:
    def _clean(v: Any) -> Optional[float]:
        if isinstance(v, (int, float)) and float(v) > 0:
            return float(v)
        return None

    teaching = _clean(reviews.get("teaching"))
    grading = _clean(reviews.get("grading"))
    workload = _clean(reviews.get("workload"))
    content = _clean(reviews.get("content"))
    overall_raw = _clean(reviews.get("overall"))

    # Recover content if only overall + 3 dimensions exist.
    if (
        content is None
        and overall_raw is not None
        and teaching is not None
        and grading is not None
        and workload is not None
    ):
        recovered = (4.0 * overall_raw) - teaching - grading - workload
        if recovered > 0:
            content = recovered

    overall: Optional[float] = None
    if content is not None and teaching is not None and grading is not None and workload is not None:
        overall = (content + teaching + grading + workload) / 4.0

    return {
        "overall": overall,
        "content": content,
        "teaching": teaching,
        "grading": grading,
        "workload": workload,
    }


def _node_color_style(color_hex: str, selected: bool) -> dict[str, Any]:
    border = "#000000" if selected else "#1d3557"
    return {
        "background": color_hex,
        "border": border,
        "highlight": {"background": color_hex, "border": "#000000"},
        "hover": {"background": color_hex, "border": border},
    }


def _detail_heading(title: str) -> None:
    st.markdown(
        f"""
        <div style="margin-top:22px; margin-bottom:8px; border:1px solid #d0d7de; border-left:6px solid #1d3557; border-radius:6px; padding:8px 10px; font-weight:700; background:#f8fafc;">
            {title}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _rating_cell_color(letter: str) -> str:
    if letter in {"A+", "A", "A-"}:
        return "#1b5e20"
    if letter in {"B+", "B", "B-"}:
        return "#558b2f"
    if letter in {"C+", "C", "C-"}:
        return "#f9a825"
    if letter in {"D+", "D", "D-"}:
        return "#ef6c00"
    if letter == "E":
        return "#8e0000"
    return "#6b7280"


def _render_review_table(reviews: dict[str, Optional[float]]) -> None:
    labels = [
        ("Overall", _rating_letter(reviews.get("overall"))),
        ("Content", _rating_letter(reviews.get("content"))),
        ("Teaching", _rating_letter(reviews.get("teaching"))),
        ("Grading", _rating_letter(reviews.get("grading"))),
        ("Workload", _rating_letter(reviews.get("workload"))),
    ]
    rows_html = []
    for label, letter in labels:
        color = _rating_cell_color(letter)
        rows_html.append(
            f"<tr><td style='padding:6px 10px; border:1px solid #d1d5db; font-weight:600;'>{label}</td>"
            f"<td style='padding:6px 10px; border:1px solid #d1d5db; font-weight:700; text-align:center; color:#fff; background:{color};'>{letter}</td></tr>"
        )
    table_html = "<table style='border-collapse:collapse; width:340px; table-layout:fixed;'>" + "".join(rows_html) + "</table>"
    st.markdown(table_html, unsafe_allow_html=True)


@st.cache_data
def list_semesters() -> list[str]:
    snapshot_root = PROJECT_ROOT / "data" / "snapshots"
    if not snapshot_root.exists():
        return []

    semesters: list[str] = []
    for child in snapshot_root.iterdir():
        if not child.is_dir():
            continue
        if (child / "graph_payload.json").exists():
            semesters.append(child.name)
    semesters.sort(reverse=True)
    return semesters


@st.cache_data
def load_graph_payload(semester: str) -> dict[str, Any]:
    graph_file = PROJECT_ROOT / "data" / "snapshots" / semester / "graph_payload.json"
    with graph_file.open("r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def load_canonical_payload(semester: str) -> dict[str, Any]:
    canonical_file = PROJECT_ROOT / "data" / "snapshots" / semester / "canonical_courses.json"
    with canonical_file.open("r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def load_raw_course_codes(semester: str) -> set[str]:
    raw_file = PROJECT_ROOT / "data" / "snapshots" / semester / "raw_courses.json"
    if not raw_file.exists():
        return set()
    with raw_file.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    out: set[str] = set()
    for course in payload.get("courses", []):
        code = str(course.get("course_code", "")).strip().upper()
        if code:
            out.add(code)
    return out


@st.cache_data
def load_review_count_map(semester: str) -> dict[str, int]:
    bundle = _term_bundle_for_year(semester)
    candidates = [bundle["spring"], bundle["fall"], bundle["winter"], bundle["summer"]]
    review_file: Optional[Path] = None
    for term in candidates:
        maybe = PROJECT_ROOT / "data" / "snapshots" / term / "ustspace_reviews.json"
        if maybe.exists():
            review_file = maybe
            break
    if review_file is None:
        return {}

    with review_file.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    explicit: dict[str, int] = {}
    counter: Counter[str] = Counter()
    for row in payload.get("reviews", []):
        code = str(row.get("course_code", "")).strip().upper()
        if code:
            explicit_count = row.get("review_count")
            if isinstance(explicit_count, (int, float)) and int(explicit_count) >= 0:
                explicit[code] = int(explicit_count)
            counter[code] += 1
    for code, c in counter.items():
        explicit.setdefault(code, c)
    return explicit


def _paired_fall_spring(semester: str) -> tuple[str, str]:
    if len(semester) == 4 and semester.isdigit():
        yy = semester[:2]
        term = semester[2:]
        if term == "10":
            return f"{yy}10", f"{yy}30"
        if term == "30":
            return f"{yy}10", f"{yy}30"
    return "2510", "2530"


def _term_bundle_for_year(semester: str) -> dict[str, str]:
    if len(semester) == 4 and semester.isdigit():
        yy = semester[:2]
    else:
        yy = "25"
    return {
        "fall": f"{yy}10",
        "winter": f"{yy}20",
        "spring": f"{yy}30",
        "summer": f"{yy}40",
    }


def _term_membership_label(course_code: str, fall_codes: set[str], spring_codes: set[str]) -> str:
    in_fall = course_code in fall_codes
    in_spring = course_code in spring_codes
    if in_fall and in_spring:
        return "both"
    if in_fall:
        return "fall"
    if in_spring:
        return "spring"
    return "none"


def _term_membership_label_4(
    course_code: str,
    *,
    fall_codes: set[str],
    winter_codes: set[str],
    spring_codes: set[str],
    summer_codes: set[str],
) -> str:
    in_fall = course_code in fall_codes
    in_winter = course_code in winter_codes
    in_spring = course_code in spring_codes
    in_summer = course_code in summer_codes

    if in_fall and in_spring and not in_winter and not in_summer:
        return "fall_spring"
    if in_fall and not in_winter and not in_spring and not in_summer:
        return "fall"
    if in_spring and not in_fall and not in_winter and not in_summer:
        return "spring"
    if in_winter and not in_fall and not in_spring and not in_summer:
        return "winter"
    if in_summer and not in_fall and not in_winter and not in_spring:
        return "summer"
    if in_fall or in_winter or in_spring or in_summer:
        return "multi"
    return "none"


def _term_color(label: str) -> str:
    if label == "fall_spring":
        return "#7cc6fe"
    if label == "fall":
        return "#f4a261"
    if label == "winter":
        return "#ffd166"
    if label == "spring":
        return "#2a9d8f"
    if label == "summer":
        return "#8ecae6"
    if label == "multi":
        return "#c77dff"
    return "#dddddd"


def _term_flags(
    course_code: str,
    *,
    fall_codes: set[str],
    winter_codes: set[str],
    spring_codes: set[str],
    summer_codes: set[str],
) -> tuple[bool, bool, bool, bool]:
    return (
        course_code in fall_codes,
        course_code in winter_codes,
        course_code in spring_codes,
        course_code in summer_codes,
    )


def _include_by_term_mode(
    course_code: str,
    *,
    term_mode: str,
    fall_codes: set[str],
    winter_codes: set[str],
    spring_codes: set[str],
    summer_codes: set[str],
) -> bool:
    if term_mode == "all":
        return (
            course_code in fall_codes
            or course_code in winter_codes
            or course_code in spring_codes
            or course_code in summer_codes
        )
    # fall_spring: include courses that appear in fall OR spring (not exclusive).
    return (course_code in fall_codes) or (course_code in spring_codes)


def _term_label_for_mode(
    course_code: str,
    *,
    term_mode: str,
    fall_codes: set[str],
    winter_codes: set[str],
    spring_codes: set[str],
    summer_codes: set[str],
) -> str:
    if term_mode == "all":
        return _term_membership_label_4(
            course_code,
            fall_codes=fall_codes,
            winter_codes=winter_codes,
            spring_codes=spring_codes,
            summer_codes=summer_codes,
        )
    two = _term_membership_label(course_code, fall_codes, spring_codes)
    return "fall_spring" if two == "both" else two


def _course_stem(course_code: str) -> str:
    m = re.search(r"^([A-Z]{3,5})\s+(\d{4})", course_code.upper())
    if not m:
        return course_code.upper()
    return f"{m.group(1)} {m.group(2)}"


def _semester_display_options(semesters: list[str]) -> tuple[list[str], dict[str, tuple[str, str]]]:
    labels: list[str] = []
    mapping: dict[str, tuple[str, str]] = {}

    prefix_25 = [s for s in semesters if s.startswith("25")]
    if prefix_25:
        base = "2530" if "2530" in semesters else prefix_25[0]
        labels.extend(["2025-2026 All", "2025-2026 Fall (F/S)"])
        mapping["2025-2026 All"] = (base, "all")
        mapping["2025-2026 Fall (F/S)"] = (base, "fall_spring")

    for s in semesters:
        label = _format_semester_label(s)
        labels.append(label)
        mapping[label] = (s, "all")
    return labels, mapping


def _split_node_svg_data_uri(
    *,
    label: str,
    left_color: str,
    right_color: str,
    selected: bool,
) -> str:
    stroke = "#ffd166" if selected else "#1d3557"
    stroke_width = "4" if selected else "2"
    safe_label = html.escape(label)
    svg = f"""
<svg xmlns='http://www.w3.org/2000/svg' width='230' height='74' viewBox='0 0 230 74'>
  <clipPath id='clip'>
    <rect x='2' y='2' rx='10' ry='10' width='226' height='70' />
  </clipPath>
  <g clip-path='url(#clip)'>
    <rect x='2' y='2' width='113' height='70' fill='{left_color}' />
    <rect x='115' y='2' width='113' height='70' fill='{right_color}' />
  </g>
  <rect x='2' y='2' rx='10' ry='10' width='226' height='70' fill='none' stroke='{stroke}' stroke-width='{stroke_width}' />
  <text x='115' y='45' text-anchor='middle' font-family='Segoe UI, Arial, sans-serif' font-size='21' font-weight='700' fill='#0f172a'>{safe_label}</text>
</svg>
""".strip()
    return f"data:image/svg+xml;utf8,{quote(svg)}"


def _tag_dictionary(canonical_payload: dict[str, Any]) -> list[dict[str, Any]]:
    tag_map: dict[str, dict[str, Any]] = {}
    for course in canonical_payload.get("courses", []):
        code = str(course.get("course_code", ""))
        for tag in course.get("special_tags", []) or []:
            if tag not in tag_map:
                tag_map[tag] = {"tag": tag, "count": 0, "examples": []}
            tag_map[tag]["count"] += 1
            examples: list[str] = tag_map[tag]["examples"]
            if code and code not in examples and len(examples) < 5:
                examples.append(code)

    rows = list(tag_map.values())
    rows.sort(key=lambda r: (-r["count"], r["tag"]))
    return rows


def _build_export_html(
    *,
    semester: str,
    nodes_data: list[dict[str, Any]],
    edges_data: list[dict[str, Any]],
) -> str:
    nodes_json = json.dumps(nodes_data, ensure_ascii=True)
    edges_json = json.dumps(edges_data, ensure_ascii=True)
    title = f"UST CourseMap View ({semester})"
    return f"""<!doctype html>
<html lang='en'>
<head>
    <meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1'>
    <title>{title}</title>
    <script type='text/javascript' src='https://unpkg.com/vis-network/standalone/umd/vis-network.min.js'></script>
    <style>
        body {{ margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; background: #f6f8fa; }}
        .top {{ padding: 10px 14px; background: #1d3557; color: #fff; font-weight: 600; }}
        #graph {{ width: 100vw; height: calc(100vh - 44px); }}
    </style>
</head>
<body>
    <div class='top'>{title}</div>
    <div id='graph'></div>
    <script>
        const nodes = new vis.DataSet({nodes_json});
        const edges = new vis.DataSet({edges_json});
        const container = document.getElementById('graph');
        const data = {{ nodes, edges }};
        const options = {{
            physics: {{ enabled: false }},
            layout: {{ hierarchical: {{ enabled: true, direction: 'LR', sortMethod: 'directed' }} }},
            interaction: {{ hover: true, navigationButtons: true }},
            edges: {{
                arrows: {{ to: {{ enabled: true, scaleFactor: 0.7 }} }},
                smooth: {{ enabled: true, type: 'horizontal', roundness: 0.0 }}
            }},
            nodes: {{ shape: 'box', margin: 8, font: {{ size: 15 }} }}
        }};
        new vis.Network(container, data, options);
    </script>
</body>
</html>"""


def _subject_prefix(course_code: str) -> str:
    return course_code.split(" ", 1)[0].upper() if course_code else ""


def _course_search_options(payload: dict[str, Any], subject_allow: set[str]) -> list[str]:
    options: list[str] = []
    for node in payload.get("nodes", []):
        code = str(node.get("id", "")).strip()
        title = str(node.get("hover", {}).get("title", "")).strip()
        if not code:
            continue
        if subject_allow and _subject_prefix(code) not in subject_allow:
            continue
        options.append(f"{code} - {title}" if title else code)
    options.sort()
    return options


def _subject_grid_positions(subjects: list[str], columns: int = 10) -> dict[str, tuple[int, int]]:
    positions: dict[str, tuple[int, int]] = {}
    x_gap = 520
    y_gap = 180
    for idx, subject in enumerate(subjects):
        row = idx // columns
        col = idx % columns
        positions[subject] = (col * x_gap, row * y_gap)
    return positions


def _format_semester_label(semester: str) -> str:
    if len(semester) != 4 or not semester.isdigit():
        return semester

    year_start_short = int(semester[:2])
    year_start = 2000 + year_start_short
    year_end = year_start + 1
    term_code = semester[2:]
    term_map = {
        "10": "Fall",
        "20": "Winter",
        "30": "Spring",
        "40": "Summer",
    }
    term_name = term_map.get(term_code, f"Term {term_code}")
    return f"{year_start}-{year_end} {term_name}"


def _build_undirected_graph(edges: list[dict[str, Any]], relation_allow: set[str]) -> nx.Graph:
    g = nx.Graph()
    for edge in edges:
        relation = edge.get("relation")
        if relation not in relation_allow:
            continue
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        if src and tgt:
            g.add_edge(src, tgt)
    return g


def _directed_focus_nodes(
    selected: Optional[str],
    edges: list[dict[str, Any]],
    relation_allow: set[str],
) -> set[str]:
    if not selected:
        return set()

    dg = nx.DiGraph()
    for edge in edges:
        relation = edge.get("relation")
        if relation not in relation_allow:
            continue
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        if src and tgt:
            dg.add_edge(src, tgt)

    if selected not in dg:
        return {selected}

    up = nx.ancestors(dg, selected)
    down = nx.descendants(dg, selected)
    return set(up).union(down).union({selected})


def _component_nodes_for_selected(
    selected: Optional[str],
    edges: list[dict[str, Any]],
    relation_allow: set[str],
) -> set[str]:
    if not selected:
        return set()
    g = _build_undirected_graph(edges, relation_allow)
    if selected not in g:
        return {selected}
    return set(nx.node_connected_component(g, selected))


def _edge_color(relation: str) -> str:
    if relation == "pre_req":
        return "#104d8d"
    if relation == "co_req":
        return "#0f8b8d"
    return "#b23a48"


def _edge_title(edge: dict[str, Any]) -> str:
    relation = edge.get("relation", "")
    if relation == "pre_req":
        rel_name = "Pre-req"
    elif relation == "co_req":
        rel_name = "Co-req"
    else:
        rel_name = "Exclusion"
    return f"{rel_name}: {edge.get('source')} => {edge.get('target')}"


def _course_thousand_digit(course_code: str) -> int:
    match = re.search(r"\b(\d{4})[A-Z]?\b", course_code.upper())
    if not match:
        return 4
    num = match.group(1)
    digit = int(num[0])
    return max(0, min(9, digit))


def _node_title(node: dict[str, Any]) -> str:
    hover = node.get("hover", {})
    tags = hover.get("special_tags", [])
    tags_text = " ".join(f"[{x}]" for x in tags) if tags else "-"
    reviews = hover.get("reviews", {})
    letters = _rating_quadletters(reviews)
    # Keep tooltip text plain (no HTML links) to avoid component double-click URL navigation.
    return (
        f"{hover.get('course_code', node.get('id'))} | "
        f"{hover.get('title', '')} | "
        f"Tags: {tags_text} | "
        f"O/T/W/G: {letters}"
    )


def _build_subject_overview_elements(
    payload: dict[str, Any],
    *,
    relation_allow: set[str],
    subject_allow: set[str],
    completed_courses: set[str],
    fall_codes: set[str],
    winter_codes: set[str],
    spring_codes: set[str],
    summer_codes: set[str],
    hidden_wcq_missing_codes: set[str],
    term_mode: str,
) -> tuple[list[Node], list[Edge], set[str], list[dict[str, Any]], list[dict[str, Any]]]:
    all_nodes: list[dict[str, Any]] = payload.get("nodes", [])
    all_edges: list[dict[str, Any]] = payload.get("edges", [])

    subject_counts: dict[str, int] = {}
    subject_completed_counts: dict[str, int] = {}
    for node in all_nodes:
        code = str(node.get("id", "")).strip()
        if not code:
            continue
        if code in hidden_wcq_missing_codes:
            continue
        if not _include_by_term_mode(
            code,
            term_mode=term_mode,
            fall_codes=fall_codes,
            winter_codes=winter_codes,
            spring_codes=spring_codes,
            summer_codes=summer_codes,
        ):
            continue
        subject = _subject_prefix(code)
        if not subject:
            continue
        if subject_allow and subject not in subject_allow:
            continue
        subject_counts[subject] = subject_counts.get(subject, 0) + 1
        if code in completed_courses:
            subject_completed_counts[subject] = subject_completed_counts.get(subject, 0) + 1

    edge_agg: dict[tuple[str, str, str], int] = {}
    for edge in all_edges:
        relation = str(edge.get("relation", ""))
        if relation not in relation_allow:
            continue
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        src_subject = _subject_prefix(src)
        tgt_subject = _subject_prefix(tgt)
        if not src_subject or not tgt_subject:
            continue
        if src_subject not in subject_counts or tgt_subject not in subject_counts:
            continue
        key = (src_subject, tgt_subject, relation)
        edge_agg[key] = edge_agg.get(key, 0) + 1

    nodes: list[Node] = []
    nodes_data: list[dict[str, Any]] = []
    ordered_subjects = sorted(subject_counts.keys())
    positions = _subject_grid_positions(ordered_subjects)
    for subject in ordered_subjects:
        count = subject_counts[subject]
        completed_count = subject_completed_counts.get(subject, 0)
        pos_x, pos_y = positions[subject]
        color = "#b7efc5" if completed_count > 0 else "#f1faee"
        title = f"<b>{subject}</b><br/>Courses: {count}<br/>Completed: {completed_count}"
        label = f"{subject} ({count})"
        nodes.append(
            Node(
                id=subject,
                label=label,
                title=None,
                div={"innerHTML": ""},
                shape="box",
                color=_node_color_style(color, False),
                borderWidth=3,
                margin=18,
                x=pos_x,
                y=pos_y,
                physics=False,
                fixed={"x": True, "y": True},
                font={"color": "#1d3557", "size": 22},
            )
        )
        nodes_data.append(
            {
                "id": subject,
                "label": label,
                "title": title,
                "shape": "box",
                "color": color,
                "borderWidth": 3,
            }
        )

    edges: list[Edge] = []
    edges_data: list[dict[str, Any]] = []
    for (src_subject, tgt_subject, relation), count in sorted(edge_agg.items()):
        color = _edge_color(relation)
        dashed = relation == "exclusion"
        title = f"{relation}: {src_subject} => {tgt_subject} ({count})"
        edges.append(
            Edge(
                source=src_subject,
                target=tgt_subject,
                color=color,
                dashes=dashed,
                width=2,
                label=str(count),
                title=title,
                smooth={"enabled": True, "type": "horizontal", "roundness": 0.0},
            )
        )
        edges_data.append(
            {
                "from": src_subject,
                "to": tgt_subject,
                "color": color,
                "dashes": dashed,
                "width": 2,
                "label": str(count),
                "title": title,
                "smooth": {"enabled": True, "type": "horizontal", "roundness": 0.0},
            }
        )

    return nodes, edges, set(subject_counts.keys()), nodes_data, edges_data


def _build_graph_elements(
    payload: dict[str, Any],
    *,
    selected: Optional[str],
    relation_allow: set[str],
    subject_allow: set[str],
    search_text: str,
    completed_courses: set[str],
    fall_codes: set[str],
    winter_codes: set[str],
    spring_codes: set[str],
    summer_codes: set[str],
    hidden_wcq_missing_codes: set[str],
    term_mode: str,
    focus_root: Optional[str] = None,
) -> tuple[list[Node], list[Edge], set[str], list[dict[str, Any]], list[dict[str, Any]]]:
    all_nodes: list[dict[str, Any]] = payload.get("nodes", [])
    all_edges: list[dict[str, Any]] = payload.get("edges", [])

    node_map = {str(n.get("id")): n for n in all_nodes}

    displayed_node_ids = set(node_map.keys())
    displayed_node_ids = {
        code
        for code in displayed_node_ids
        if code not in hidden_wcq_missing_codes
        and _include_by_term_mode(
            code,
            term_mode=term_mode,
            fall_codes=fall_codes,
            winter_codes=winter_codes,
            spring_codes=spring_codes,
            summer_codes=summer_codes,
        )
    }
    if subject_allow:
        displayed_node_ids = {
            node_id
            for node_id in displayed_node_ids
            if _subject_prefix(node_id) in subject_allow
        }

    # Keep full filtered view on selection; only highlight and detail panel should change.

    query = search_text.strip().upper()
    if query:
        matched = {
            node_id
            for node_id, node in node_map.items()
            if query in node_id.upper() or query in str(node.get("hover", {}).get("title", "")).upper()
        }
        if selected:
            displayed_node_ids = displayed_node_ids.intersection(matched.union({selected}))
        else:
            displayed_node_ids = matched

    if focus_root:
        focus_nodes = _directed_focus_nodes(focus_root, all_edges, relation_allow)
        displayed_node_ids = displayed_node_ids.intersection(focus_nodes)

    nodes: list[Node] = []
    nodes_data: list[dict[str, Any]] = []

    # Composite layering score: lower-thousand courses + high prereq influence + central nodes go higher.
    pre_req_out_count: dict[str, int] = {node_id: 0 for node_id in displayed_node_ids}
    total_degree_count: dict[str, int] = {node_id: 0 for node_id in displayed_node_ids}
    pre_req_graph = nx.DiGraph()
    pre_req_graph.add_nodes_from(displayed_node_ids)

    for edge in all_edges:
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        if src in total_degree_count:
            total_degree_count[src] += 1
        if tgt in total_degree_count:
            total_degree_count[tgt] += 1

        if edge.get("relation") == "pre_req" and src in pre_req_out_count and tgt in displayed_node_ids:
            pre_req_out_count[src] += 1
            pre_req_graph.add_edge(src, tgt)

    reverse_pagerank: dict[str, float] = {node_id: 0.0 for node_id in displayed_node_ids}
    if pre_req_graph.number_of_nodes() > 0 and pre_req_graph.number_of_edges() > 0:
        try:
            reverse_pagerank = nx.pagerank(pre_req_graph.reverse(copy=False), alpha=0.85)
        except Exception:
            reverse_pagerank = {node_id: 0.0 for node_id in displayed_node_ids}

    rank_values = sorted(reverse_pagerank.values()) if reverse_pagerank else [0.0]
    rank_min = rank_values[0] if rank_values else 0.0
    rank_max = rank_values[-1] if rank_values else 0.0

    score_map: dict[str, float] = {}
    for node_id in displayed_node_ids:
        thousand = _course_thousand_digit(node_id)
        thousand_score = float(max(0, 6 - thousand))
        prereq_score = math.log1p(pre_req_out_count.get(node_id, 0))
        degree_score = math.log1p(total_degree_count.get(node_id, 0))
        pr = reverse_pagerank.get(node_id, 0.0)
        pr_norm = 0.0 if rank_max <= rank_min else (pr - rank_min) / (rank_max - rank_min)

        score_map[node_id] = (2.2 * thousand_score) + (1.6 * prereq_score) + (1.1 * degree_score) + (2.0 * pr_norm)

    ranked_ids = sorted(displayed_node_ids, key=lambda n: (score_map.get(n, 0.0), n), reverse=True)
    node_count = max(1, len(ranked_ids))
    # High-score nodes are placed near center; low-score nodes move toward outer rings.
    rings = max(5, min(16, int(round(math.sqrt(node_count) * 1.35))))
    level_map: dict[str, int] = {}
    for idx, node_id in enumerate(ranked_ids):
        ring = int((idx * rings) / node_count)
        level_map[node_id] = ring + 1

    # Cluster same stem variants (e.g. COMP 4971 A/B/...) onto the same column.
    stem_groups: dict[str, list[str]] = {}
    for node_id in displayed_node_ids:
        stem_groups.setdefault(_course_stem(node_id), []).append(node_id)
    for members in stem_groups.values():
        if len(members) <= 1:
            continue
        base_level = min(level_map.get(member, 1) for member in members)
        for member in members:
            level_map[member] = base_level

    ring_members: dict[int, list[str]] = {}
    for node_id in displayed_node_ids:
        ring_members.setdefault(level_map.get(node_id, 1), []).append(node_id)

    ring_gap = 320
    positions: dict[str, tuple[float, float]] = {}
    for ring in sorted(ring_members.keys()):
        members = sorted(ring_members[ring])
        radius = ring * ring_gap
        count = len(members)
        for i, node_id in enumerate(members):
            angle = (2.0 * math.pi * i) / max(1, count)
            positions[node_id] = (radius * math.cos(angle), radius * math.sin(angle))

    for node_id in sorted(displayed_node_ids):
        node = node_map.get(node_id)
        if not node:
            continue
        term_label = _term_label_for_mode(
            node_id,
            term_mode=term_mode,
            fall_codes=fall_codes,
            winter_codes=winter_codes,
            spring_codes=spring_codes,
            summer_codes=summer_codes,
        )
        color = _term_color(term_label)
        color_style = _node_color_style(color, False)
        pos_x, pos_y = positions.get(node_id, (0.0, 0.0))
        nodes.append(
            Node(
                id=node_id,
                label=node.get("label", node_id),
                title=None,
                # Prevent streamlit-agraph doubleClick handler from opening URLs.
                div={"innerHTML": ""},
                shape="box",
                color=color_style,
                borderWidth=2,
                margin=12,
                x=pos_x,
                y=pos_y,
                physics=False,
                fixed={"x": True, "y": True},
                font={"color": "#1d3557", "size": 18},
            )
        )
        nodes_data.append(
            {
                "id": node_id,
                "label": node.get("label", node_id),
                "title": _node_title(node),
                "shape": "box",
                "color": color,
                "borderWidth": 2,
            }
        )

    node_id_set = {n.id for n in nodes}
    edges: list[Edge] = []
    edges_data: list[dict[str, Any]] = []
    for edge in all_edges:
        relation = edge.get("relation")
        if relation not in relation_allow:
            continue
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        if src not in node_id_set or tgt not in node_id_set:
            continue

        style = edge.get("style", {})
        dashed = bool(style.get("line_style") == "dashed")
        color = _edge_color(str(relation))

        edges.append(
            Edge(
                source=src,
                target=tgt,
                color=color,
                dashes=dashed,
                width=2,
                title=_edge_title(edge),
                smooth={"enabled": True, "type": "horizontal", "roundness": 0.0},
            )
        )
        edges_data.append(
            {
                "from": src,
                "to": tgt,
                "color": color,
                "dashes": dashed,
                "width": 2,
                "title": _edge_title(edge),
                "smooth": {"enabled": True, "type": "horizontal", "roundness": 0.0},
            }
        )

    return nodes, edges, displayed_node_ids, nodes_data, edges_data


def _get_node_details(payload: dict[str, Any], node_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not node_id:
        return None
    for node in payload.get("nodes", []):
        if str(node.get("id")) == node_id:
            details = node.get("details", {})
            if isinstance(details, dict):
                return details
    return None


def _related_relations(payload: dict[str, Any], node_id: Optional[str]) -> dict[str, list[str]]:
    out = {
        "pre_reqs": [],
        "co_reqs": [],
        "exclusions": [],
        "required_by": [],
        "corequired_by": [],
        "excluded_by": [],
    }
    if not node_id:
        return out

    for edge in payload.get("edges", []):
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        relation = str(edge.get("relation", ""))
        if relation == "pre_req":
            if tgt == node_id:
                out["pre_reqs"].append(src)
            if src == node_id:
                out["required_by"].append(tgt)
        elif relation == "co_req":
            if tgt == node_id:
                out["co_reqs"].append(src)
            if src == node_id:
                out["corequired_by"].append(tgt)
        elif relation == "exclusion":
            if src == node_id:
                out["exclusions"].append(tgt)
            if tgt == node_id:
                out["excluded_by"].append(src)

    for key in out:
        out[key] = sorted(set(out[key]))
    return out


def main() -> None:
    st.set_page_config(page_title="UST CourseMap", layout="wide")
    st.title("UST CourseMap")
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 0.8rem;
        }
        div[data-testid="stButton"] button[kind="primary"] {
            background-color: #1f9d55;
            color: #ffffff;
            border: 1px solid #1f9d55;
            font-weight: 700;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border: 2px solid #000 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    raw_semesters = list_semesters()
    if not raw_semesters:
        st.error("No graph payload found. Run: python scripts/build_m3_model.py 2530")
        return

    semester_labels, semester_map = _semester_display_options(raw_semesters)

    with st.sidebar:
        semester_label = st.selectbox(
            "Semester",
            semester_labels,
            index=0,
        )
        selected_semester, term_mode = semester_map[semester_label]

    payload = load_graph_payload(selected_semester)
    canonical_payload = load_canonical_payload(selected_semester)

    if "selected_course" not in st.session_state:
        st.session_state.selected_course = None
    if "focus_root" not in st.session_state:
        st.session_state.focus_root = None
    if "last_click_course" not in st.session_state:
        st.session_state.last_click_course = None
    if "last_click_ts" not in st.session_state:
        st.session_state.last_click_ts = 0.0
    if "selected_subject" not in st.session_state:
        st.session_state.selected_subject = None
    if "completed_courses" not in st.session_state:
        st.session_state.completed_courses = []
    if "show_completed_add" not in st.session_state:
        st.session_state.show_completed_add = False

    subject_options = sorted(
        {
            _subject_prefix(str(node.get("id", "")))
            for node in payload.get("nodes", [])
            if str(node.get("id", "")).strip()
        }
    )

    relation_allow = {"pre_req", "co_req", "exclusion"}
    term_bundle = _term_bundle_for_year(selected_semester)
    fall_codes = load_raw_course_codes(term_bundle["fall"])
    winter_codes = load_raw_course_codes(term_bundle["winter"])
    spring_codes = load_raw_course_codes(term_bundle["spring"])
    summer_codes = load_raw_course_codes(term_bundle["summer"])
    review_count_map = load_review_count_map(selected_semester)

    wcq_union_codes = set().union(fall_codes, winter_codes, spring_codes, summer_codes)
    ustspace_once_codes: set[str] = set(review_count_map.keys())
    hidden_wcq_missing_codes = ustspace_once_codes - wcq_union_codes

    with st.sidebar:
        st.markdown("### Filters")
        subject_allow = set(
            st.multiselect(
                "Subject filter (e.g. COMP, ECON)",
                subject_options,
                default=[],
                key="subject_filter",
            )
        )
        search_subject_scope = set(subject_allow)
        if st.session_state.selected_subject:
            search_subject_scope = {st.session_state.selected_subject}
        search_options = _course_search_options(payload, search_subject_scope)
        search_pick = st.selectbox(
            "Search course code/title",
            options=search_options,
            index=None,
            placeholder="Type code/title and select suggestion",
            accept_new_options=True,
        )

    all_courses = sorted(
        [str(node.get("id", "")) for node in payload.get("nodes", []) if str(node.get("id", ""))]
    )

    with st.sidebar:
        st.markdown("### Completed Courses")
        st.caption("One course per row. Click '-' on the right to remove.")
        st.session_state.completed_courses = [
            c for c in st.session_state.completed_courses if c in all_courses
        ]
        completed_sorted = sorted(set(st.session_state.completed_courses))

        if st.button("Add", type="primary"):
            st.session_state.show_completed_add = not st.session_state.show_completed_add
            st.rerun()

        if st.session_state.show_completed_add:
            with st.form("completed_add_form", clear_on_submit=True):
                add_codes = st.multiselect(
                    "Select courses to add",
                    options=all_courses,
                    default=[],
                )
                col_a, col_b = st.columns(2)
                submitted = col_a.form_submit_button("Confirm Add", type="primary")
                canceled = col_b.form_submit_button("Cancel", type="primary")

            if submitted:
                merged = sorted(set(st.session_state.completed_courses).union(set(add_codes)))
                st.session_state.completed_courses = merged
                st.session_state.show_completed_add = False
                st.rerun()
            if canceled:
                st.session_state.show_completed_add = False
                st.rerun()

        if not completed_sorted:
            st.write("(none)")
        for code in completed_sorted:
            left_col, right_col = st.columns([5, 1], vertical_alignment="center")
            left_col.write(code)
            key = f"remove_completed_{code.replace(' ', '_')}"
            with right_col:
                if st.button("-", key=key, type="primary"):
                    st.session_state.completed_courses = [
                        c for c in st.session_state.completed_courses if c != code
                    ]
                    st.rerun()

    query_text = ""
    if isinstance(search_pick, str) and search_pick.strip():
        query_text = search_pick.split(" - ", 1)[0].strip()

    effective_subject_allow = set(subject_allow)
    if st.session_state.selected_subject:
        effective_subject_allow = {st.session_state.selected_subject}

    show_course_level = bool(st.session_state.selected_subject or query_text)
    selected_course = st.session_state.selected_course

    if show_course_level:
        nodes, edges, displayed_node_ids, nodes_data, edges_data = _build_graph_elements(
            payload,
            selected=selected_course,
            relation_allow=relation_allow,
            subject_allow=effective_subject_allow,
            search_text=query_text,
            completed_courses=set(st.session_state.completed_courses),
            fall_codes=fall_codes,
            winter_codes=winter_codes,
            spring_codes=spring_codes,
            summer_codes=summer_codes,
            hidden_wcq_missing_codes=hidden_wcq_missing_codes,
            term_mode=term_mode,
            focus_root=st.session_state.focus_root,
        )
    else:
        nodes, edges, displayed_node_ids, nodes_data, edges_data = _build_subject_overview_elements(
            payload,
            relation_allow=relation_allow,
            subject_allow=effective_subject_allow,
            completed_courses=set(st.session_state.completed_courses),
            fall_codes=fall_codes,
            winter_codes=winter_codes,
            spring_codes=spring_codes,
            summer_codes=summer_codes,
            hidden_wcq_missing_codes=hidden_wcq_missing_codes,
            term_mode=term_mode,
        )

    if not nodes:
        st.warning("No courses matched current search/filter. Try widening keyword or clearing subject filters.")
        return

    if show_course_level and (len(nodes) > 700 or len(edges) > 1800):
        st.error(
            "Result set is too large and may cause rendering/read errors. Narrow by course code and/or subject filter."
        )
        return

    export_html = _build_export_html(
        semester=selected_semester,
        nodes_data=nodes_data,
        edges_data=edges_data,
    )

    with st.sidebar:
        st.markdown("### Export")
        st.download_button(
            "Download Current View (HTML)",
            data=export_html,
            file_name=f"ust-coursemap-{selected_semester}-view.html",
            mime="text/html",
        )

        tag_rows = _tag_dictionary(canonical_payload)
        st.markdown("### Tag Dictionary")
        st.caption(f"{len(tag_rows)} tags in this semester")
        with st.expander("Show Tags (count + examples)", expanded=False):
            for row in tag_rows:
                examples = ", ".join(row["examples"]) if row["examples"] else "-"
                meaning = row.get("meaning", "") or "(no meaning inferred)"
                st.write(f"[{row['tag']}]  x{row['count']}  |  {meaning}  |  {examples}")

        missing_list = sorted(hidden_wcq_missing_codes)
        with st.expander("USTSpace-only (not in WCQ terms)", expanded=False):
            st.caption(f"{len(missing_list)} courses")
            if missing_list:
                st.write("\n".join(missing_list))
            else:
                st.write("(none)")

    graph_level_name = "course" if show_course_level else "subject"
    st.markdown(
        f"Graph Level: `{graph_level_name}` | Displayed Nodes: `{len(nodes)}` | Displayed Edges: `{len(edges)}` | Selected Course: `{selected_course or '-'}`"  # noqa: E501
    )
    st.caption("Color legend is fixed at top-right of the graph.")

    if show_course_level:
        st.caption("Click a course node to focus its related chain. Layout is static.")
        if st.button("Back To Subject Overview", type="secondary"):
            st.session_state.selected_subject = None
            st.session_state.selected_course = None
            st.session_state.focus_root = None
            st.rerun()
    else:
        st.caption("Default subject overview: SUBJECT (count). Click a subject node to focus that subject.")

    config = Config(
        width=1800,
        height=760,
        directed=True,
        physics=False,
        hierarchical=False,
    )

    graph_box = st.container(border=True)
    try:
        with graph_box:
            st.markdown(
                """
                <div style="position:relative; height:0;">
                    <div style="position:absolute; top:8px; right:10px; z-index:999; pointer-events:none; background:rgba(255,255,255,0.93); border:1px solid #222; border-radius:8px; padding:8px 10px; font-size:12px; line-height:1.35; width:max-content; max-width:300px;">
                        <div style="font-weight:700; margin-bottom:6px;">Node Colors</div>
                        <div><span style="display:inline-block;width:12px;height:12px;background:#7cc6fe;border:1px solid #555;margin-right:6px;vertical-align:middle;"></span>Fall &amp; Spring</div>
                        <div><span style="display:inline-block;width:12px;height:12px;background:#f4a261;border:1px solid #555;margin-right:6px;vertical-align:middle;"></span>Fall only</div>
                        <div><span style="display:inline-block;width:12px;height:12px;background:#ffd166;border:1px solid #555;margin-right:6px;vertical-align:middle;"></span>Winter only</div>
                        <div><span style="display:inline-block;width:12px;height:12px;background:#2a9d8f;border:1px solid #555;margin-right:6px;vertical-align:middle;"></span>Spring only</div>
                        <div><span style="display:inline-block;width:12px;height:12px;background:#8ecae6;border:1px solid #555;margin-right:6px;vertical-align:middle;"></span>Summer only</div>
                        <div><span style="display:inline-block;width:12px;height:12px;background:#c77dff;border:1px solid #555;margin-right:6px;vertical-align:middle;"></span>Multi-term</div>
                        <div style="font-weight:700; margin-top:8px; margin-bottom:6px;">Edge Colors</div>
                        <div><span style="display:inline-block;width:18px;border-top:3px solid #104d8d;margin-right:6px;vertical-align:middle;"></span>Pre-req</div>
                        <div><span style="display:inline-block;width:18px;border-top:3px solid #0f8b8d;margin-right:6px;vertical-align:middle;"></span>Co-req</div>
                        <div><span style="display:inline-block;width:18px;border-top:3px dashed #b23a48;margin-right:6px;vertical-align:middle;"></span>Exclusion</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            picked = agraph(nodes=nodes, edges=edges, config=config)
    except Exception as exc:
        st.error(f"Graph render failed (read error): {exc}")
        st.info("Please narrow search/filter and retry.")
        return

    if isinstance(picked, str):
        picked = picked.strip()
        if picked:
            if show_course_level:
                now_ts = time.time()
                is_double = (
                    st.session_state.last_click_course == picked
                    and (now_ts - float(st.session_state.last_click_ts)) < 0.6
                )
                st.session_state.selected_course = picked
                if is_double:
                    if st.session_state.focus_root == picked:
                        st.session_state.focus_root = None
                    else:
                        st.session_state.focus_root = picked
                else:
                    st.session_state.focus_root = None
                st.session_state.last_click_course = picked
                st.session_state.last_click_ts = now_ts
            elif picked in subject_options:
                st.session_state.selected_subject = picked
                st.session_state.selected_course = None
                st.session_state.focus_root = None
                st.rerun()

    details = _get_node_details(payload, st.session_state.selected_course)
    relations = _related_relations(payload, st.session_state.selected_course)

    if not details:
        if show_course_level:
            st.info("Click a course node to show its connected chain and full details.")
        return

    st.markdown("---")
    st.subheader(str(details.get("course_code", "")))
    st.write(str(details.get("title", "")))

    tags = details.get("special_tags", [])
    if isinstance(tags, list) and tags:
        st.markdown(" ".join(f"`[{x}]`" for x in tags))

    raw_reviews = details.get("reviews", {}) if isinstance(details.get("reviews"), dict) else {}
    reviews = _normalize_reviews_for_display(raw_reviews)
    course_code_for_count = str(details.get("course_code", st.session_state.selected_course or "")).strip().upper()
    review_count = details.get("review_count")
    if not (isinstance(review_count, int) and review_count >= 0):
        review_count = review_count_map.get(course_code_for_count)
    if not (isinstance(review_count, int) and review_count >= 0):
        if any(isinstance(v, (int, float)) and float(v) > 0 for v in raw_reviews.values()):
            review_count = 1
    review_count_text = str(review_count) if isinstance(review_count, int) and review_count >= 0 else "N/A"
    _detail_heading(f"Ratings (Reviews: {review_count_text})")
    _render_review_table(reviews)

    description = str(details.get("description", "")).strip()
    if description:
        _detail_heading("Description")
        st.write(description)

    attributes_text = str(details.get("attributes_text", "")).strip()
    if attributes_text:
        _detail_heading("Attributes")
        st.write(attributes_text)

    cross_campus = str(details.get("cross_campus_course_equivalence", "")).strip()
    if cross_campus:
        _detail_heading("Cross Campus Course Equivalence")
        st.write(cross_campus)

    alternate_codes = str(details.get("alternate_codes", "")).strip()
    if alternate_codes:
        _detail_heading("Alternate Code(s)")
        st.write(alternate_codes)

    pre_raw = str(details.get("raw_pre_req_text", "")).strip()
    co_raw = str(details.get("raw_co_req_text", "")).strip()
    ex_raw = str(details.get("raw_exclusion_text", "")).strip()
    if pre_raw or co_raw or ex_raw:
        _detail_heading("Requirements & Exclusions")
        if pre_raw:
            st.write(f"Pre-req raw: {pre_raw}")
        if co_raw:
            st.write(f"Co-req raw: {co_raw}")
        if ex_raw:
            st.write(f"Exclusion raw: {ex_raw}")

    _detail_heading("Relations (Current Graph Scope)")
    st.write(f"pre_reqs: {', '.join(relations['pre_reqs']) or '-'}")
    st.write(f"co_reqs: {', '.join(relations['co_reqs']) or '-'}")
    st.write(f"exclusions: {', '.join(relations['exclusions']) or '-'}")
    st.write(f"required_by: {', '.join(relations['required_by']) or '-'}")
    st.write(f"corequired_by: {', '.join(relations['corequired_by']) or '-'}")
    st.write(f"excluded_by: {', '.join(relations['excluded_by']) or '-'}")

    sections = details.get("sections", [])
    if isinstance(sections, list) and sections:
        _detail_heading("Sections")
        rows: list[dict[str, Any]] = []
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            rows.append(
                {
                    "Section": sec.get("section", ""),
                    "Date/Time": sec.get("date_time", ""),
                    "Room": sec.get("room", ""),
                    "Instructor": sec.get("instructor", ""),
                    "TA/IA/GTA": sec.get("ta_ia_gta", ""),
                    "Remarks": sec.get("remarks", ""),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
