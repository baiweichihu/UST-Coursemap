import argparse
import json
from pathlib import Path


def review_snapshot_path(project_root: Path, semester: str) -> Path:
    return project_root / "data" / "snapshots" / semester / "ustspace_reviews.json"


def build_report(semester: str, reviews: list[dict]) -> dict:
    keys = ("overall", "teaching", "workload", "grading")
    total = len(reviews)

    matched_nonnull = sum(1 for r in reviews if any(r.get(k) is not None for k in keys))
    matched_positive = sum(1 for r in reviews if any((r.get(k) or 0) > 0 for k in keys))
    all_null = sum(1 for r in reviews if all(r.get(k) is None for k in keys))
    all_zero = sum(1 for r in reviews if all(r.get(k) == 0 for k in keys))
    existing_pages = total - all_null

    ratio_nonnull_all = (matched_nonnull / total) if total else 0.0
    ratio_nonnull_existing_pages = (matched_nonnull / existing_pages) if existing_pages else 0.0
    ratio_positive_all = (matched_positive / total) if total else 0.0
    ratio_positive_existing_pages = (matched_positive / existing_pages) if existing_pages else 0.0

    return {
        "semester": semester,
        "total_courses": total,
        "review_page_exists_count": existing_pages,
        "matched_nonnull_count": matched_nonnull,
        "matched_positive_count": matched_positive,
        "all_zero_count": all_zero,
        "all_null_count": all_null,
        "ratio_nonnull_all": ratio_nonnull_all,
        "ratio_nonnull_existing_pages": ratio_nonnull_existing_pages,
        "ratio_positive_all": ratio_positive_all,
        "ratio_positive_existing_pages": ratio_positive_existing_pages,
    }


def write_back_metrics(payload: dict, report: dict, review_file: Path) -> None:
    coverage_stats = {
        "coverage_semester": report["semester"],
        "coverage_total_courses": report["total_courses"],
        "coverage_review_page_exists_count": report["review_page_exists_count"],
        "coverage_matched_nonnull_count": report["matched_nonnull_count"],
        "coverage_matched_positive_count": report["matched_positive_count"],
        "coverage_ratio_nonnull_all": report["ratio_nonnull_all"],
        "coverage_ratio_positive_all": report["ratio_positive_all"],
        "coverage_ratio_nonnull_existing_pages": report["ratio_nonnull_existing_pages"],
        "coverage_ratio_positive_existing_pages": report["ratio_positive_existing_pages"],
    }

    # Keep source review entries unchanged and persist aggregate coverage metadata.
    payload.update(coverage_stats)
    review_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze USTSpace review coverage by denominator.")
    parser.add_argument("semester", help="Semester code in xxyy format, e.g. 2530")
    parser.add_argument(
        "--write-back",
        action="store_true",
        help="Write computed coverage metrics back into ustspace_reviews.json",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    review_file = review_snapshot_path(root, args.semester)
    if not review_file.exists():
        raise RuntimeError(f"USTSpace snapshot missing: {review_file}")

    payload = json.loads(review_file.read_text(encoding="utf-8"))
    reviews = payload.get("reviews", [])
    report = build_report(args.semester, reviews)

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.write_back:
        write_back_metrics(payload, report, review_file)
        print("write-back: updated ustspace_reviews.json with coverage metrics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
