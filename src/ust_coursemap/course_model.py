import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from ust_coursemap.prereq_parser import (
    collect_course_codes_from_tree,
    normalize_course_code,
    parse_exclusions,
    parse_requirement_expression,
)


@dataclass
class CanonicalCourse:
    course_code: str
    title: str
    credits: Optional[int]
    description: str
    attributes_text: str
    special_tags: list[str]
    pre_reqs: Optional[dict[str, Any]]
    co_reqs: Optional[dict[str, Any]]
    exclusions: list[str]
    reviews: dict[str, Optional[float]]
    raw_pre_req_text: str
    raw_co_req_text: str
    raw_exclusion_text: str
    sections: list[dict[str, str]]


def _extract_bracket_tags_in_order(text: str) -> list[str]:
    out: list[str] = []
    for content in re.findall(r"\[([^\]]+)\]", text.upper()):
        for part in re.split(r"[\s,;/]+", content):
            token = part.strip()
            if token and token not in out:
                out.append(token)
    return out


def _cc_suffix(attributes_text: str, tag: str) -> Optional[str]:
    text = attributes_text.upper()
    if tag == "CC22":
        pattern = r"COMMON\s+CORE\s*\(([^\)]+)\)\s*FOR\s*30-CREDIT\s*PROG\s*IN\s*22-24"
    else:
        pattern = r"COMMON\s+CORE\s*\(([^\)]+)\)\s*FOR\s*30-CREDIT\s*PROG\s*F(?:R|ROM)\s*25"

    match = re.search(pattern, text)
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(1).strip())


def _normalize_special_tags(
    base_tags: list[str],
    *,
    attributes_text: str,
    section_remarks_text: str,
) -> list[str]:
    tags = list(base_tags)
    material = f"{attributes_text} {section_remarks_text}".upper()

    if re.search(r"36-CREDIT\s+PROGRAM", material) and "4Y" not in tags:
        tags.append("4Y")

    if _cc_suffix(attributes_text, "CC22") and "CC22" not in tags and not any(t.startswith("CC22-") for t in tags):
        tags.append("CC22")

    if _cc_suffix(attributes_text, "CC25") and "CC25" not in tags and not any(t.startswith("CC25-") for t in tags):
        tags.append("CC25")

    if re.search(r"\bBLD\b|BLENDED", material) and "BLD" not in tags:
        tags.append("BLD")

    if re.search(r"\bSPO\b|SELF[-\s]?PACED|SELF[-\s]?STUDY", material) and "SPO" not in tags:
        tags.append("SPO")

    if "DELI" in tags:
        replacement = "SPO"
        if re.search(r"\bBLD\b|BLENDED", material):
            replacement = "BLD"
        elif re.search(r"\bSPO\b|SELF[-\s]?PACED|SELF[-\s]?STUDY", material):
            replacement = "SPO"
        tags = [replacement if t == "DELI" else t for t in tags]

    normalized: list[str] = []
    for tag in tags:
        if tag == "CC22":
            suffix = _cc_suffix(attributes_text, "CC22")
            tag = f"CC22-{suffix}" if suffix else "CC22"
        elif tag == "CC25":
            suffix = _cc_suffix(attributes_text, "CC25")
            tag = f"CC25-{suffix}" if suffix else "CC25"

        if tag not in normalized:
            normalized.append(tag)

    return normalized


def _normalize_review(raw: dict[str, Any]) -> dict[str, Optional[float]]:
    out: dict[str, Optional[float]] = {
        "overall": None,
        "teaching": None,
        "workload": None,
        "grading": None,
    }
    for key in out.keys():
        value = raw.get(key)
        if isinstance(value, (int, float)):
            out[key] = float(value)
            continue
        if isinstance(value, str):
            try:
                out[key] = float(value)
            except ValueError:
                out[key] = None
    return out


def build_canonical_courses(merged_payload: dict[str, Any]) -> list[CanonicalCourse]:
    courses: list[CanonicalCourse] = []
    for item in merged_payload.get("courses", []):
        code = normalize_course_code(str(item.get("course_code", "")))
        title = str(item.get("title", "")).strip()
        description = str(item.get("description", "")).strip()
        pre_text = str(item.get("pre_req_text", "")).strip()
        co_text = str(item.get("co_req_text", "")).strip()
        exclusion_text = str(item.get("exclusion_text", "")).strip()
        attributes_text = str(item.get("attributes_text", "")).strip()
        raw_sections = item.get("sections", [])
        sections: list[dict[str, str]] = []
        for section in raw_sections if isinstance(raw_sections, list) else []:
            if not isinstance(section, dict):
                continue
            sections.append(
                {
                    "section": str(section.get("section", "")),
                    "date_time": str(section.get("date_time", "")),
                    "room": str(section.get("room", "")),
                    "instructor": str(section.get("instructor", "")),
                    "ta_ia_gta": str(section.get("ta_ia_gta", "")),
                    "remarks": str(section.get("remarks", "")),
                }
            )

        section_remarks = " ".join(s.get("remarks", "") for s in sections)
        base_tags = _extract_bracket_tags_in_order(attributes_text)
        special_tags = _normalize_special_tags(
            base_tags,
            attributes_text=attributes_text,
            section_remarks_text=section_remarks,
        )

        courses.append(
            CanonicalCourse(
                course_code=code,
                title=title,
                credits=item.get("credits"),
                description=description,
                attributes_text=attributes_text,
                special_tags=special_tags,
                pre_reqs=parse_requirement_expression(pre_text),
                co_reqs=parse_requirement_expression(co_text),
                exclusions=parse_exclusions(exclusion_text),
                reviews=_normalize_review(item.get("reviews", {})),
                raw_pre_req_text=pre_text,
                raw_co_req_text=co_text,
                raw_exclusion_text=exclusion_text,
                sections=sections,
            )
        )
    return courses


def _node_payload(course: CanonicalCourse) -> dict[str, Any]:
    return {
        "id": course.course_code,
        "label": course.course_code,
        "shape": "rectangle",
        "hover": {
            "course_code": course.course_code,
            "title": course.title,
            "special_tags": course.special_tags,
            "reviews": course.reviews,
        },
        "details": asdict(course),
    }


def _edge_style(relation: str, is_mutual_exclusion: bool) -> dict[str, Any]:
    if relation == "pre_req":
        return {
            "line_style": "solid",
            "arrow": "single_direction_double_head_solid",
            "show_logic_label": False,
        }
    if relation == "co_req":
        return {
            "line_style": "solid",
            "arrow": "single_direction_single_head_solid",
            "show_logic_label": False,
        }
    return {
        "line_style": "dashed",
        "arrow": "single_direction_single_head_solid",
        "show_logic_label": False,
        "is_mutual_exclusion": is_mutual_exclusion,
    }


def _edge_id(source: str, target: str, relation: str) -> str:
    return f"{relation}:{source}->{target}"


def build_graph_payload(courses: list[CanonicalCourse]) -> dict[str, Any]:
    node_map: dict[str, dict[str, Any]] = {}
    edge_map: dict[str, dict[str, Any]] = {}

    for course in courses:
        node_map[course.course_code] = _node_payload(course)

    def ensure_placeholder(code: str) -> None:
        if code in node_map:
            return
        node_map[code] = {
            "id": code,
            "label": code,
            "shape": "rectangle",
            "hover": {
                "course_code": code,
                "title": "(Not in semester snapshot)",
                "special_tags": [],
                "reviews": {
                    "overall": None,
                    "teaching": None,
                    "workload": None,
                    "grading": None,
                },
            },
            "details": {
                "course_code": code,
                "title": "(Not in semester snapshot)",
                "credits": None,
                "description": "",
                "special_tags": [],
                "pre_reqs": None,
                "co_reqs": None,
                "exclusions": [],
                "reviews": {
                    "overall": None,
                    "teaching": None,
                    "workload": None,
                    "grading": None,
                },
                "raw_pre_req_text": "",
                "raw_co_req_text": "",
                "raw_exclusion_text": "",
            },
        }

    for course in courses:
        for req_code in collect_course_codes_from_tree(course.pre_reqs):
            ensure_placeholder(req_code)
            edge_id = _edge_id(req_code, course.course_code, "pre_req")
            edge_map[edge_id] = {
                "id": edge_id,
                "source": req_code,
                "target": course.course_code,
                "relation": "pre_req",
                "style": _edge_style("pre_req", False),
            }

        for req_code in collect_course_codes_from_tree(course.co_reqs):
            ensure_placeholder(req_code)
            edge_id = _edge_id(req_code, course.course_code, "co_req")
            edge_map[edge_id] = {
                "id": edge_id,
                "source": req_code,
                "target": course.course_code,
                "relation": "co_req",
                "style": _edge_style("co_req", False),
            }

        for excluded in course.exclusions:
            ensure_placeholder(excluded)
            edge_id = _edge_id(course.course_code, excluded, "exclusion")
            edge_map[edge_id] = {
                "id": edge_id,
                "source": course.course_code,
                "target": excluded,
                "relation": "exclusion",
                "style": _edge_style("exclusion", False),
            }

    # Mark two directed exclusion edges as a mutual exclusion pair.
    for edge in edge_map.values():
        if edge["relation"] != "exclusion":
            continue
        rev_id = _edge_id(edge["target"], edge["source"], "exclusion")
        if rev_id in edge_map:
            edge["style"] = _edge_style("exclusion", True)

    return {
        "nodes": sorted(node_map.values(), key=lambda n: n["id"]),
        "edges": sorted(edge_map.values(), key=lambda e: e["id"]),
    }


def build_related_chain(graph_payload: dict[str, Any], course_code: str) -> dict[str, Any]:
    code = normalize_course_code(course_code)
    node_ids = {node["id"] for node in graph_payload.get("nodes", [])}
    if code not in node_ids:
        return {"nodes": [], "edges": []}

    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    edge_lookup: list[dict[str, Any]] = graph_payload.get("edges", [])

    for edge in edge_lookup:
        src = edge.get("source")
        tgt = edge.get("target")
        if src in adjacency and tgt in adjacency:
            adjacency[src].add(tgt)
            adjacency[tgt].add(src)

    visited: set[str] = set()
    queue = [code]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for nxt in adjacency.get(current, set()):
            if nxt not in visited:
                queue.append(nxt)

    nodes = [n for n in graph_payload.get("nodes", []) if n.get("id") in visited]
    edges = [
        e
        for e in edge_lookup
        if e.get("source") in visited or e.get("target") in visited
    ]
    return {
        "nodes": sorted(nodes, key=lambda n: n["id"]),
        "edges": sorted(edges, key=lambda e: e["id"]),
    }


def load_merged_snapshot(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_m3_outputs_from_merged(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    merged_payload = load_merged_snapshot(path)
    courses = build_canonical_courses(merged_payload)
    course_payload = {
        "semester": merged_payload.get("semester"),
        "generated_at_epoch": merged_payload.get("generated_at_epoch"),
        "course_count": len(courses),
        "courses": [asdict(c) for c in courses],
    }
    graph_payload = {
        "semester": merged_payload.get("semester"),
        "generated_at_epoch": merged_payload.get("generated_at_epoch"),
        **build_graph_payload(courses),
    }
    return course_payload, graph_payload
