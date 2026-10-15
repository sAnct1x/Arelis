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


# --- an empty result must not read like a broken tool -----------------------


async def test_no_matching_rows_says_so_and_shows_the_filter(tool, table):
    result = await _q(tool, table, where="region == atlantis", on="revenue")
    assert result.ok
    assert "0 of 6 rows matched" in result.output
    assert "atlantis" in result.output
    assert "No rows to aggregate" in result.output


# --- the mistakes a model will actually make --------------------------------


async def test_or_is_refused_with_a_way_around_it(tool, table):
    result = await _q(tool, table, where="region == north or region == south")
    assert not result.ok
    assert "`or` is not supported" in result.output
    assert "in" in result.output


# --- the reason this is not DataFrame.query() -------------------------------


# --- the parser on its own ---------------------------------------------------


def test_a_condition_with_no_operator_is_refused():
    with pytest.raises(QueryError):
        parse_condition("just some words")


# --- the other actions are untouched ----------------------------------------


