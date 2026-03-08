import argparse
import json
from pathlib import Path

from ust_coursemap.course_model import build_m3_outputs_from_merged
from ust_coursemap.wcq_crawler import validate_semester


def merged_snapshot_path(project_root: Path, semester: str) -> Path:
    return project_root / "data" / "snapshots" / semester / "merged_courses.json"


def canonical_snapshot_path(project_root: Path, semester: str) -> Path:
    return project_root / "data" / "snapshots" / semester / "canonical_courses.json"


def graph_snapshot_path(project_root: Path, semester: str) -> Path:
    return project_root / "data" / "snapshots" / semester / "graph_payload.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Milestone 3 canonical model + graph payload.")
    parser.add_argument("semester", help="Semester code in xxyy format, e.g. 2530")
    args = parser.parse_args()

    semester = validate_semester(args.semester)
    root = Path(__file__).resolve().parents[1]
    merged_file = merged_snapshot_path(root, semester)
    if not merged_file.exists():
        raise RuntimeError(f"Merged snapshot missing: {merged_file}")

    canonical_payload, graph_payload = build_m3_outputs_from_merged(merged_file)

    canonical_file = canonical_snapshot_path(root, semester)
    graph_file = graph_snapshot_path(root, semester)
    canonical_file.parent.mkdir(parents=True, exist_ok=True)

    canonical_file.write_text(json.dumps(canonical_payload, indent=2, ensure_ascii=True), encoding="utf-8")
    graph_file.write_text(json.dumps(graph_payload, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Canonical model created: {canonical_file}")
    print(f"Graph payload created: {graph_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
