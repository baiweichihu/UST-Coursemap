from ust_coursemap.prereq_parser import (
    collect_course_codes_from_tree,
    parse_exclusions,
    parse_requirement_expression,
)


def test_parse_simple_and_or() -> None:
    tree = parse_requirement_expression("COMP 2011 AND (MATH 1012 OR MATH 1020)")
    assert tree is not None
    assert tree["type"] == "and"

    children = tree["children"]
    assert children[0]["type"] == "course"
    assert children[0]["course_code"] == "COMP 2011"
    assert children[1]["type"] == "or"


def test_parse_implicit_and() -> None:
    tree = parse_requirement_expression("COMP2011 MATH1012")
    assert tree is not None
    assert tree["type"] == "and"
    assert [x["course_code"] for x in tree["children"]] == ["COMP 2011", "MATH 1012"]


def test_parse_slash_as_or() -> None:
    tree = parse_requirement_expression("ISOM 2500 / MATH 2011")
    assert tree is not None
    assert tree["type"] == "or"
    assert [x["course_code"] for x in tree["children"]] == ["ISOM 2500", "MATH 2011"]


def test_parse_exclusions() -> None:
    codes = parse_exclusions("Exclusion: COMP1021, COMP 1022Q, and ISOM2500")
    assert codes == ["COMP 1021", "COMP 1022Q", "ISOM 2500"]


def test_collect_unique_course_codes() -> None:
    tree = parse_requirement_expression("(COMP2011 OR COMP2011H) AND (MATH1012 OR MATH1012)")
    codes = collect_course_codes_from_tree(tree)
    assert codes == ["COMP 2011", "COMP 2011H", "MATH 1012"]
