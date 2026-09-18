"""The query action: can analyze answer a question, and can it be made to eval?

Two halves. The first is whether a data question that used to require reading
rows and adding them up now comes back as a number. The second is whether the
`where` string is a way into `eval`, which it would have been had this been
built on `DataFrame.query()`.
"""

from __future__ import annotations

import pytest

from arelis.tools.analyze import (
    AnalyzeTool,
    QueryError,
    parse_condition,
    split_conditions,
)

pytestmark = pytest.mark.anyio

CSV = """date,region,product,units,revenue,status
2026-01-04,north,widget,3,30.5,shipped
2026-02-11,north,widget,5,52.0,shipped
2026-03-02,south,gizmo,2,88.0,pending
2026-03-14,north,gizmo,7,301.25,shipped
2026-03-19,south,widget,1,11.0,cancelled
2026-04-01,east,gizmo,4,160.0,shipped
"""


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def table(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text(CSV, encoding="utf-8")
    return path


@pytest.fixture
def tool(tmp_path):
    return AnalyzeTool([str(tmp_path)])


async def _q(tool, path, **kwargs):
    return await tool.run(path=str(path), action="query", **kwargs)


# --- the question that used to require mental arithmetic --------------------


async def test_a_total_comes_back_as_a_number(tool, table):
    result = await _q(tool, table, on="revenue")
    assert result.ok
    assert "642.75" in result.output


async def test_a_filtered_total_is_the_filtered_total(tool, table):
    result = await _q(tool, table, where="status == shipped", on="revenue")
    assert result.ok
    # 30.5 + 52.0 + 301.25 + 160.0
    assert "543.75" in result.output
    assert "4 of 6 rows matched" in result.output


async def test_the_scale_of_the_answer_is_always_stated(tool, table):
    """ "543.75" alone invites reporting it as the whole file's total."""
    result = await _q(tool, table, where="region == north", on="revenue")
    assert "3 of 6 rows matched" in result.output


async def test_grouping_answers_the_by_something_question(tool, table):
    result = await _q(tool, table, group_by="region", on="revenue", agg="sum")
    assert result.ok
    assert "north" in result.output and "383.75" in result.output
    assert "south" in result.output and "99" in result.output


async def test_group_with_no_on_counts_rows(tool, table):
    result = await _q(tool, table, group_by="status")
    assert result.ok
    assert "count" in result.output
    assert "shipped" in result.output


async def test_sort_and_limit_give_a_top_n(tool, table):
    result = await _q(tool, table, sort="revenue", desc=True, limit=2)
    assert result.ok
    lines = [ln for ln in result.output.splitlines() if "gizmo" in ln or "widget" in ln]
    assert len(lines) == 2
    assert "301.25" in lines[0]


async def test_select_narrows_the_columns(tool, table):
    result = await _q(tool, table, select="region,revenue", limit=2)
    assert result.ok
    assert "region" in result.output
    assert "product" not in result.output


async def test_contains_matches_text_without_a_regex(tool, table):
    result = await _q(tool, table, where="date contains 2026-03", on="revenue")
    assert result.ok
    assert "3 of 6" in result.output
    assert "400.25" in result.output


async def test_in_takes_a_list(tool, table):
    result = await _q(tool, table, where="region in north,east", on="units")
    assert result.ok
    assert "19" in result.output


async def test_two_conditions_join_with_and(tool, table):
    result = await _q(tool, table, where="status == shipped and units > 3", on="revenue")
    assert result.ok
    assert "3 of 6" in result.output
    assert "513.25" in result.output


# --- an empty result must not read like a broken tool -----------------------


async def test_no_matching_rows_says_so_and_shows_the_filter(tool, table):
    result = await _q(tool, table, where="region == atlantis", on="revenue")
    assert result.ok
    assert "0 of 6 rows matched" in result.output
    assert "atlantis" in result.output
    assert "No rows to aggregate" in result.output


async def test_an_empty_result_reports_no_total(tool, table):
    """A sum of nothing is 0, and reporting "0" would be a wrong answer."""
    result = await _q(tool, table, where="units > 999", on="revenue")
    assert "0.0" not in result.output.replace("0 of 6", "")


# --- the mistakes a model will actually make --------------------------------


async def test_a_wrong_column_name_lists_the_real_ones(tool, table):
    result = await _q(tool, table, on="sales")
    assert not result.ok
    assert "no column named 'sales'" in result.output
    assert "revenue" in result.output


async def test_case_is_forgiven_on_column_names(tool, table):
    result = await _q(tool, table, on="Revenue")
    assert result.ok
    assert "642.75" in result.output


async def test_or_is_refused_with_a_way_around_it(tool, table):
    result = await _q(tool, table, where="region == north or region == south")
    assert not result.ok
    assert "`or` is not supported" in result.output
    assert "in" in result.output


async def test_a_nonsense_condition_explains_the_grammar(tool, table):
    result = await _q(tool, table, where="revenue is large")
    assert not result.ok
    assert "could not read condition" in result.output
    assert "contains" in result.output


async def test_an_unknown_agg_lists_the_known_ones(tool, table):
    result = await _q(tool, table, on="revenue", agg="average")
    assert not result.ok
    assert "mean" in result.output


# --- the reason this is not DataFrame.query() -------------------------------


async def test_a_where_string_cannot_write_a_file(tool, table, tmp_path):
    """The payload here is the one that works, not the one that looks scary.

    The first version of this test used `@__import__(...)`, and it passed even
    with the parser swapped for `DataFrame.query()` — pandas blocks `__import__`
    by name, so the test proved nothing about the thing it was named for. What
    pandas does allow is an attribute chain off any name in the caller's frame,
    and `df` is always in that frame. `@df.to_csv(path)` writes a real file and
    only then fails on the mask, so the write has already happened.
    """
    escape = tmp_path / "pwned.csv"
    result = await _q(tool, table, where=f"@df.to_csv({str(escape)!r})")
    assert not result.ok
    assert not escape.exists()


async def test_a_where_string_cannot_run_a_command(tool, table, tmp_path):
    """`asyncio` is a module global in analyze.py, so this chain is in scope.

    Verified against `DataFrame.query()` directly: it executes. That is the
    whole argument for the hand-written parser two files over.
    """
    marker = tmp_path / "ran.txt"
    # as_posix, because a Windows path inside the literal makes it a
    # SyntaxError — which would make this test pass without proving a thing.
    hostile = f"@asyncio.base_events.os.system('echo x > {marker.as_posix()}')"
    result = await _q(tool, table, where=hostile)
    assert not result.ok
    assert not marker.exists()


async def test_a_dunder_in_a_condition_is_just_a_missing_column(tool, table):
    result = await _q(tool, table, where="__class__ == x")
    assert not result.ok
    assert "no column named" in result.output


async def test_arithmetic_in_a_condition_is_not_computed(tool, table):
    """No evaluator means `units * 2` is a column name, and there isn't one."""
    result = await _q(tool, table, where="units * 2 > 4")
    assert not result.ok
    assert "no column named" in result.output


async def test_a_backtick_column_does_not_become_an_expression(tool, table):
    result = await _q(tool, table, where="`units` > 4")
    assert result.ok
    assert "2 of 6" in result.output


# --- the parser on its own ---------------------------------------------------


def test_the_longer_operator_wins():
    assert parse_condition("a >= 3") == ("a", ">=", 3)
    assert parse_condition("a != 3") == ("a", "!=", 3)


def test_a_quoted_value_stays_text():
    """Leading zeros are the reason quoting exists: 007 is not 7."""
    assert parse_condition("sku == '007'") == ("sku", "==", "007")


def test_an_unquoted_number_becomes_one():
    _column, _op, value = parse_condition("n == 3")
    assert isinstance(value, int) and value == 3


def test_a_bare_word_stays_a_word():
    assert parse_condition("s == shipped") == ("s", "==", "shipped")


def test_a_condition_with_no_operator_is_refused():
    with pytest.raises(QueryError):
        parse_condition("just some words")


def test_a_condition_with_no_column_is_refused():
    with pytest.raises(QueryError):
        parse_condition("== 3")


def test_conditions_split_on_and_only():
    assert split_conditions("a == 1 and b == 2") == ["a == 1", "b == 2"]


def test_a_column_named_android_does_not_split():
    """`and` inside a word is not a conjunction, and the \\s+ guards say so."""
    assert split_conditions("android == 1") == ["android == 1"]


# --- the other actions are untouched ----------------------------------------


async def test_summary_still_works(tool, table):
    result = await tool.run(path=str(table), action="summary")
    assert result.ok
    assert "6 rows" in result.output


async def test_head_still_works(tool, table):
    result = await tool.run(path=str(table), action="head", rows=2)
    assert result.ok
    assert "gizmo" not in result.output.split("\n")[1]
