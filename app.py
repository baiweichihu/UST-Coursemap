import json
import sys
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
    if value is None:
        return "N/A"
    if value >= 4.5:
        return "A"
    if value >= 3.5:
        return "B"
    if value >= 2.5:
        return "C"
    if value >= 1.5:
        return "D"
    return "E"


def _rating_quadletters(reviews: dict[str, Optional[float]]) -> str:
    overall = _rating_letter(reviews.get("overall"))
    teaching = _rating_letter(reviews.get("teaching"))
    workload = _rating_letter(reviews.get("workload"))
    grading = _rating_letter(reviews.get("grading"))
    return f"{overall}/{teaching}/{workload}/{grading}"


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


def _build_search_suggestions(payload: dict[str, Any], query: str, limit: int = 30) -> list[str]:
    q = query.strip().upper()
    if not q:
        return []

    suggestions: list[str] = []
    for node in payload.get("nodes", []):
        code = str(node.get("id", "")).strip()
        title = str(node.get("hover", {}).get("title", "")).strip()
        if not code:
            continue
        if q in code.upper() or q in title.upper():
            suggestions.append(f"{code} - {title}" if title else code)
    suggestions.sort()
    return suggestions[:limit]


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


def _node_title(node: dict[str, Any]) -> str:
    hover = node.get("hover", {})
    tags = hover.get("special_tags", [])
    tags_text = " ".join(f"[{x}]" for x in tags) if tags else "-"
    reviews = hover.get("reviews", {})
    letters = _rating_quadletters(reviews)
    return (
        f"<b>{hover.get('course_code', node.get('id'))}</b><br/>"
        f"{hover.get('title', '')}<br/>"
        f"Tags: {tags_text}<br/>"
        f"O/T/W/G: {letters}"
    )


def _build_graph_elements(
    payload: dict[str, Any],
    *,
    selected: Optional[str],
    relation_allow: set[str],
    subject_allow: set[str],
    search_text: str,
    completed_courses: set[str],
    max_nodes_display: int,
) -> tuple[list[Node], list[Edge], set[str], list[dict[str, Any]], list[dict[str, Any]]]:
    all_nodes: list[dict[str, Any]] = payload.get("nodes", [])
    all_edges: list[dict[str, Any]] = payload.get("edges", [])

    node_map = {str(n.get("id")): n for n in all_nodes}

    displayed_node_ids = set(node_map.keys())
    if subject_allow:
        displayed_node_ids = {
            node_id
            for node_id in displayed_node_ids
            if _subject_prefix(node_id) in subject_allow
        }

    if selected:
        displayed_node_ids = _component_nodes_for_selected(selected, all_edges, relation_allow)
        if subject_allow:
            displayed_node_ids = {
                node_id
                for node_id in displayed_node_ids
                if _subject_prefix(node_id) in subject_allow or node_id == selected
            }

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

    if max_nodes_display > 0 and len(displayed_node_ids) > max_nodes_display:
        degree_map: dict[str, int] = {node_id: 0 for node_id in displayed_node_ids}
        for edge in all_edges:
            relation = edge.get("relation")
            if relation not in relation_allow:
                continue
            src = str(edge.get("source", ""))
            tgt = str(edge.get("target", ""))
            if src in degree_map:
                degree_map[src] += 1
            if tgt in degree_map:
                degree_map[tgt] += 1

        ranked = sorted(
            displayed_node_ids,
            key=lambda n: (
                1 if n == selected else 0,
                1 if n in completed_courses else 0,
                degree_map.get(n, 0),
                n,
            ),
            reverse=True,
        )
        displayed_node_ids = set(ranked[:max_nodes_display])

    nodes: list[Node] = []
    nodes_data: list[dict[str, Any]] = []
    for node_id in sorted(displayed_node_ids):
        node = node_map.get(node_id)
        if not node:
            continue
        is_selected = node_id == selected
        is_completed = node_id in completed_courses
        color = "#ffd166" if is_selected else ("#b7efc5" if is_completed else "#f1faee")
        nodes.append(
            Node(
                id=node_id,
                label=node.get("label", node_id),
                title=_node_title(node),
                shape="box",
                color=color,
                borderWidth=3 if is_selected else 1,
                font={"color": "#1d3557", "size": 15},
            )
        )
        nodes_data.append(
            {
                "id": node_id,
                "label": node.get("label", node_id),
                "title": _node_title(node),
                "shape": "box",
                "color": color,
                "borderWidth": 3 if is_selected else 1,
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
    st.set_page_config(page_title="UST CourseMap - M4", layout="wide")
    st.title("UST CourseMap - Milestone 4 Prototype")
    st.caption("Rectangular nodes, typed relations, hover details, click-to-chain focus, and full course detail panel")
    st.markdown(
        """
        <style>
        div[data-testid="stButton"] button[kind="secondary"] {
            color: #b00020;
            border-color: #b00020;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    semesters = list_semesters()
    if not semesters:
        st.error("No graph payload found. Run: python scripts/build_m3_model.py 2530")
        return

    with st.sidebar:
        semester = st.selectbox("Semester", semesters, index=0)

    payload = load_graph_payload(semester)
    canonical_payload = load_canonical_payload(semester)

    subject_options = sorted(
        {
            _subject_prefix(str(node.get("id", "")))
            for node in payload.get("nodes", [])
            if str(node.get("id", "")).strip()
        }
    )

    relation_allow = {"pre_req", "co_req", "exclusion"}

    with st.sidebar:
        st.markdown("### Snapshot Status")
        snapshot_dir = PROJECT_ROOT / "data" / "snapshots" / semester
        status_files = {
            "raw_courses.json": (snapshot_dir / "raw_courses.json").exists(),
            "ustspace_reviews.json": (snapshot_dir / "ustspace_reviews.json").exists(),
            "merged_courses.json": (snapshot_dir / "merged_courses.json").exists(),
            "canonical_courses.json": (snapshot_dir / "canonical_courses.json").exists(),
            "graph_payload.json": (snapshot_dir / "graph_payload.json").exists(),
        }
        for name, exists in status_files.items():
            st.write(f"{'OK' if exists else 'MISS'}  {name}")

        st.markdown("### Filters")
        subject_allow = set(
            st.multiselect(
                "Subject filter (e.g. COMP, ECON)",
                subject_options,
                default=[],
            )
        )
        search_text = st.text_input("Search course code/title")
        search_suggestions = _build_search_suggestions(payload, search_text)
        suggestion_pick = st.selectbox(
            "Search suggestions (live)",
            options=search_suggestions,
            index=None,
            placeholder="Type above to see matching course suggestions",
        )
        max_nodes_display = st.slider(
            "Max nodes shown (dense readability)",
            min_value=20,
            max_value=1000,
            value=200,
            step=20,
        )

    if "selected_course" not in st.session_state:
        st.session_state.selected_course = None
    if "completed_courses" not in st.session_state:
        st.session_state.completed_courses = []

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

        if st.session_state.selected_course and st.button("Add Selected As Completed", type="primary"):
            code = st.session_state.selected_course
            if code not in st.session_state.completed_courses:
                st.session_state.completed_courses = st.session_state.completed_courses + [code]
                st.rerun()

        if not completed_sorted:
            st.write("(none)")
        for code in completed_sorted:
            left_col, right_col = st.columns([5, 1], vertical_alignment="center")
            left_col.write(code)
            key = f"remove_completed_{code.replace(' ', '_')}"
            with right_col:
                if st.button("-", key=key, type="secondary"):
                    st.session_state.completed_courses = [
                        c for c in st.session_state.completed_courses if c != code
                    ]
                    st.rerun()

    query_text = suggestion_pick.split(" - ", 1)[0].strip() if suggestion_pick else search_text.strip()
    if not query_text:
        st.info("Type a course code/title in sidebar search to start.")
        return

    selected_course = st.session_state.selected_course
    nodes, edges, displayed_node_ids, nodes_data, edges_data = _build_graph_elements(
        payload,
        selected=selected_course,
        relation_allow=relation_allow,
        subject_allow=subject_allow,
        search_text=query_text,
        completed_courses=set(st.session_state.completed_courses),
        max_nodes_display=max_nodes_display,
    )

    if not nodes:
        st.warning("No courses matched current search/filter. Try widening keyword or clearing subject filters.")
        return

    if len(nodes) > 700 or len(edges) > 1800:
        st.error(
            "Result set is too large and may cause rendering/read errors. Narrow by course code and/or subject filter."
        )
        return

    export_html = _build_export_html(
        semester=semester,
        nodes_data=nodes_data,
        edges_data=edges_data,
    )

    with st.sidebar:
        st.markdown("### Export")
        st.download_button(
            "Download Current View (HTML)",
            data=export_html,
            file_name=f"ust-coursemap-{semester}-view.html",
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

    left, right = st.columns([2.1, 1], gap="large")
    with left:
        if len(displayed_node_ids) >= max_nodes_display:
            st.warning(
                "Dense mode clipped nodes to improve readability. Increase 'Max nodes shown' in sidebar for a fuller view."
            )
        st.markdown(
            f"Displayed Nodes: `{len(nodes)}` | Displayed Edges: `{len(edges)}` | Selected: `{selected_course or '-'}"  # noqa: E501
        )
        st.caption("Click a node to focus only its related chain. Layout is static (no auto motion).")
        config = Config(
            width="100%",
            height=760,
            directed=True,
            physics=False,
            hierarchical=True,
            nodeHighlightBehavior=True,
            highlightColor="#ffe082",
            collapsible=False,
            staticGraph=True,
        )
        try:
            picked = agraph(nodes=nodes, edges=edges, config=config)
        except Exception as exc:
            st.error(f"Graph render failed (read error): {exc}")
            st.info("Please narrow search/filter and retry.")
            return
        if isinstance(picked, str):
            picked = picked.strip()
            if picked:
                if st.session_state.selected_course != picked:
                    st.session_state.selected_course = picked
                    st.rerun()
            elif st.session_state.selected_course is not None:
                st.session_state.selected_course = None
                st.rerun()

    with right:
        details = _get_node_details(payload, st.session_state.selected_course)
        relations = _related_relations(payload, st.session_state.selected_course)

        if not details:
            st.info("Click a course node to show its connected chain and full details.")
            return

        st.subheader(str(details.get("course_code", "")))
        st.write(str(details.get("title", "")))

        tags = details.get("special_tags", [])
        if isinstance(tags, list) and tags:
            st.markdown(" ".join(f"`[{x}]`" for x in tags))

        reviews = details.get("reviews", {}) if isinstance(details.get("reviews"), dict) else {}
        st.markdown(f"**O/T/W/G**: `{_rating_quadletters(reviews)}`")

        st.markdown("**Description**")
        st.write(str(details.get("description", "")))

        st.markdown("**Attributes**")
        st.write(str(details.get("attributes_text", "")))

        st.markdown("**Requirements & Exclusions**")
        st.write(f"Pre-req raw: {details.get('raw_pre_req_text', '')}")
        st.write(f"Co-req raw: {details.get('raw_co_req_text', '')}")
        st.write(f"Exclusion raw: {details.get('raw_exclusion_text', '')}")

        st.markdown("**Relations (Current Graph Scope)**")
        st.write(f"pre_reqs: {', '.join(relations['pre_reqs']) or '-'}")
        st.write(f"co_reqs: {', '.join(relations['co_reqs']) or '-'}")
        st.write(f"exclusions: {', '.join(relations['exclusions']) or '-'}")
        st.write(f"required_by: {', '.join(relations['required_by']) or '-'}")
        st.write(f"corequired_by: {', '.join(relations['corequired_by']) or '-'}")
        st.write(f"excluded_by: {', '.join(relations['excluded_by']) or '-'}")

        sections = details.get("sections", [])
        if isinstance(sections, list) and sections:
            st.markdown("**Sections (without quota/enrol/avail/wait)**")
            st.json(sections)


if __name__ == "__main__":
    main()
