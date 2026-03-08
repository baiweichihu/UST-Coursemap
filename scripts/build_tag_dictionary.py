import argparse
import json
import re
from pathlib import Path


def canonical_snapshot_path(project_root: Path, semester: str) -> Path:
    return project_root / "data" / "snapshots" / semester / "canonical_courses.json"


def tag_dictionary_json_path(project_root: Path, semester: str) -> Path:
    return project_root / "data" / "snapshots" / semester / "tag_dictionary.json"


def tag_dictionary_md_path(project_root: Path, semester: str) -> Path:
    return project_root / "data" / "snapshots" / semester / "tag_dictionary.md"


def build_tag_rows(canonical_payload: dict) -> list[dict]:
    tag_map: dict[str, dict] = {}
    attribute_samples: dict[str, list[str]] = {}
    for course in canonical_payload.get("courses", []):
        code = str(course.get("course_code", "")).strip()
        title = str(course.get("title", "")).strip()
        attrs = str(course.get("attributes_text", "")).strip()

        if attrs:
            for token in re.findall(r"\[([^\]]+)\]", attrs.upper()):
                tag = token.strip()
                if not tag:
                    continue
                snippets = attribute_samples.setdefault(tag, [])
                if attrs not in snippets and len(snippets) < 20:
                    snippets.append(attrs)

        for tag in course.get("special_tags", []) or []:
            row = tag_map.setdefault(
                tag,
                {
                    "tag": tag,
                    "count": 0,
                    "examples": [],
                    "meaning": "",
                },
            )
            row["count"] += 1
            if code and len(row["examples"]) < 10:
                pair = f"{code} - {title}" if title else code
                if pair not in row["examples"]:
                    row["examples"].append(pair)

    rows = list(tag_map.values())
    for row in rows:
        row["meaning"] = infer_tag_meaning(row["tag"], attribute_samples)

    rows.sort(key=lambda r: (-r["count"], r["tag"]))
    return rows


def _extract_phrase_for_tag(tag: str, attrs: str) -> str:
    pattern = rf"\[{re.escape(tag)}\]\s*([^\[]+)"
    match = re.search(pattern, attrs.upper())
    if not match:
        return ""
    phrase = match.group(1)
    phrase = phrase.split("Common Core", 1)[0]
    phrase = phrase.split("[", 1)[0]
    phrase = re.sub(r"\s+", " ", phrase).strip(" ;,.-")
    return phrase


def infer_tag_meaning(tag: str, attribute_samples: dict[str, list[str]]) -> str:
    if tag.startswith("CC22-"):
        suffix = tag[5:]
        return f"Common Core ({suffix}) for 30-credit program in 22-24"
    if tag.startswith("CC25-"):
        suffix = tag[5:]
        return f"Common Core ({suffix}) for 30-credit program from 25"
    if tag == "4Y":
        return "Course mentions 36-credit program (4Y curriculum)"

    samples = attribute_samples.get(tag, [])
    for attrs in samples:
        phrase = _extract_phrase_for_tag(tag, attrs)
        if phrase:
            return phrase.title()

    fallback_map = {
        "BLD": "Blended learning",
        "SPO": "Special/Self-paced offering",
        "ONL": "Online mode",
        "EXP": "Experiential learning",
    }
    return fallback_map.get(tag, "(Meaning not auto-resolved from current snapshot)")


def rows_to_markdown(rows: list[dict], semester: str) -> str:
    lines = [
        f"# Tag Dictionary ({semester})",
        "",
        "| Tag | Count | Meaning | Example Courses |",
        "| --- | ---: | --- | --- |",
    ]
    for row in rows:
        examples = "; ".join(row["examples"]) if row["examples"] else "-"
        meaning = row.get("meaning", "") or "-"
        lines.append(f"| [{row['tag']}] | {row['count']} | {meaning} | {examples} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build tag dictionary from canonical snapshot.")
    parser.add_argument("semester", help="Semester code in xxyy format, e.g. 2530")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    canonical_file = canonical_snapshot_path(root, args.semester)
    if not canonical_file.exists():
        raise RuntimeError(f"Canonical snapshot missing: {canonical_file}")

    payload = json.loads(canonical_file.read_text(encoding="utf-8"))
    rows = build_tag_rows(payload)

    json_file = tag_dictionary_json_path(root, args.semester)
    md_file = tag_dictionary_md_path(root, args.semester)
    json_file.parent.mkdir(parents=True, exist_ok=True)

    json_payload = {
        "semester": args.semester,
        "tag_count": len(rows),
        "rows": rows,
    }
    json_file.write_text(json.dumps(json_payload, indent=2, ensure_ascii=True), encoding="utf-8")
    md_file.write_text(rows_to_markdown(rows, args.semester), encoding="utf-8")

    print(f"Tag dictionary JSON created: {json_file}")
    print(f"Tag dictionary Markdown created: {md_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
