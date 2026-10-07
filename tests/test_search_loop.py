"""Search, then open a hit, then search again. Any research ask."""

from arelis.core.search_loop import (
    hits_waiting,
    note_search_hits,
    page_key,
    url_is_a_hit,
)
from arelis.core.turn_context import TurnContext


def _ctx() -> TurnContext:
    return TurnContext(text="research the atmosphere and write a pdf", role="research")


def test_papers_are_listed_before_wikipedia() -> None:
    ctx = _ctx()
    note_search_hits(
        ctx,
        [
            {"url": "https://en.wikipedia.org/wiki/K2-18b", "title": "K2-18b"},
            {"url": "https://arxiv.org/abs/2309.05566", "title": "Carbon-bearing"},
            {"url": "https://example.com/news", "title": "news"},
        ],
    )
    assert ctx.last_hit_urls[0] == "https://arxiv.org/abs/2309.05566"
    assert ctx.last_hit_urls[-1].startswith("https://en.wikipedia.org/")


def test_one_opened_hit_allows_another_search() -> None:
    ctx = _ctx()
    note_search_hits(
        ctx,
        [
            {"url": "https://arxiv.org/abs/2309.05566"},
            {"url": "https://en.wikipedia.org/wiki/K2-18b"},
        ],
    )
    assert hits_waiting(ctx)
    ctx.opened_urls.add(page_key("https://arxiv.org/html/2309.05566v2"))
    assert hits_waiting(ctx) == []


def test_a_url_the_user_typed_is_allowed() -> None:
    ctx = _ctx()
    ctx.text = "Read https://arxiv.org/abs/2309.05566 and write a pdf"
    note_search_hits(
        ctx,
        [
            {"url": "https://arxiv.org/abs/2504.12267"},
            {"url": "https://en.wikipedia.org/wiki/K2-18b"},
        ],
    )
    assert url_is_a_hit(ctx, "https://arxiv.org/abs/2309.05566")
    assert not url_is_a_hit(ctx, "https://arxiv.org/abs/2309.15684")


def test_encyclopedia_only_hits_do_not_close_the_list() -> None:
    ctx = _ctx()
    note_search_hits(
        ctx,
        [
            {"url": "https://en.wikipedia.org/wiki/K2-18b"},
            {"url": "https://en.wikipedia.org/wiki/Hycean_planet"},
        ],
    )
    assert url_is_a_hit(ctx, "https://arxiv.org/abs/2309.05566")


def test_a_paper_hit_still_rejects_a_different_url() -> None:
    ctx = _ctx()
    note_search_hits(
        ctx,
        [
            {"url": "https://arxiv.org/abs/2309.05566"},
            {"url": "https://en.wikipedia.org/wiki/K2-18b"},
        ],
    )
    assert url_is_a_hit(ctx, "https://arxiv.org/html/2309.05566v2")
    assert not url_is_a_hit(ctx, "https://arxiv.org/abs/2309.15684")
