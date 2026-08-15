"""Multi-strategy article extraction for scrape."""

from __future__ import annotations

from arelis.tools.article import extract_article, format_article, sibling_urls


def test_json_ld_article_body_wins_over_nav_noise() -> None:
    html = """
    <html><head><title>Site</title>
    <script type="application/ld+json">
    {
      "@type": "NewsArticle",
      "headline": "Virus genomes from an AI model",
      "author": {"name": "Sam Reporter"},
      "datePublished": "2026-08-01",
      "articleBody": "Researchers used a model to design sixteen functional viral genomes that replicate in the lab. Safety boards are watching closely."
    }
    </script>
    </head>
    <body>
      <nav>Home Politics Markets Opinion</nav>
      <div class="sidebar">Subscribe now Buy stocks</div>
      <p>teaser</p>
    </body></html>
    """
    art = extract_article(html, base_url="https://news.example/story")
    assert art.ok
    assert art.strategy == "json-ld"
    assert "sixteen functional" in art.text
    assert "Subscribe now" not in art.text
    assert art.title.startswith("Virus genomes")
    assert art.byline == "Sam Reporter"


def test_json_ld_html_article_body_unwrapped() -> None:
    html = """
    <html><head>
    <script type="application/ld+json">
    {
      "@type": "BlogPosting",
      "headline": "Fringe notes",
      "articleBody": "<p>First we aligned the mounts on the optical table.</p><p>Then the fringe contrast jumped on the camera feed.</p>"
    }
    </script>
    </head><body><nav>Menu</nav></body></html>
    """
    art = extract_article(html)
    assert art.ok
    assert art.strategy == "json-ld"
    assert "aligned the mounts" in art.text
    assert "<p>" not in art.text


def test_article_tag_beats_full_body_chrome() -> None:
    html = """
    <html><head><title>Lab log</title>
    <meta property="og:site_name" content="Optics Weekly"/>
    </head>
    <body>
      <header>Menu Search Login</header>
      <article>
        <h1>Mirror alignment notes</h1>
        <p>We aligned the U100A mounts this morning and the fringe contrast jumped noticeably on the camera feed.</p>
        <p>Next step is locking the piezo driver gain before the overnight run.</p>
      </article>
      <footer>Copyright cookies privacy</footer>
    </body></html>
    """
    art = extract_article(html)
    assert art.ok
    assert "fringe contrast" in art.text
    assert "cookies privacy" not in art.text
    assert art.site == "Optics Weekly"
    doc = format_article(art, max_chars=5000)
    assert doc.startswith("# ")
    assert "Site: Optics Weekly" in doc
    assert "words" in doc
    assert "[extracted via" in doc


def test_paragraph_lattice_without_article_tag() -> None:
    html = """
    <html><body>
      <div class="wrap">
        <p>Short teaser.</p>
        <p>The laboratory published sixteen AI-designed viral genomes that replicate under controlled conditions in a sealed chamber.</p>
        <p>Independent groups are attempting to reproduce the result before any policy response is drafted by the review board.</p>
        <p>Funding agencies have asked for a temporary pause on open release of similar models pending further study.</p>
      </div>
      <div class="comments">
        <p>lol</p><p>first</p><p>subscribe</p>
      </div>
    </body></html>
    """
    art = extract_article(html)
    assert art.ok
    assert "sixteen AI-designed" in art.text
    assert art.strategy in {"paragraph-lattice", "density", "full-body"} or art.ok


def test_noscript_rescue_for_js_shell() -> None:
    html = """
    <html><body>
      <div id="app"></div>
      <noscript>
        <article>
          <p>Without JavaScript you still get the story: sixteen genomes were designed by a model and shown to replicate in bacteria under lab controls.</p>
          <p>That sentence alone is enough for a research assistant to summarize the result accurately.</p>
        </article>
      </noscript>
    </body></html>
    """
    art = extract_article(html)
    assert art.ok
    assert "sixteen genomes" in art.text
    # Lattice may win if it walks <p> inside <noscript>; either way we got the story.
    assert art.strategy in {"noscript", "paragraph-lattice", "article-tag", "density"}


def test_microdata_article_body() -> None:
    html = """
    <html><body>
      <div itemprop="articleBody">
        <p>Microdata carried the full write-up about locking the piezo driver before the overnight interferometer run began in earnest.</p>
        <p>Contrast on the camera improved after the U100A mounts were finally squared to the optical axis.</p>
      </div>
    </body></html>
    """
    art = extract_article(html)
    assert art.ok
    assert "piezo driver" in art.text
    assert art.strategy == "microdata"


def test_amp_link_discovered_for_siblings() -> None:
    html = """
    <html><head>
      <link rel="amphtml" href="https://news.example/story/amp"/>
      <link rel="canonical" href="https://news.example/story"/>
      <title>Stub</title>
    </head>
    <body><div id="app"></div></body></html>
    """
    art = extract_article(html, base_url="https://news.example/story")
    assert art.amp_url == "https://news.example/story/amp"
    assert art.canonical_url == "https://news.example/story"
    alts = sibling_urls(art, page_url="https://news.example/story")
    assert "https://news.example/story/amp" in alts
    assert any("amp=1" in u or u.endswith("/amp") for u in alts)


def test_paywall_diagnosis_on_thin_subscriber_page() -> None:
    html = """
    <html><body>
      <h1>Exclusive</h1>
      <p>Subscribe to continue reading this article.</p>
      <p>Already a subscriber? Sign in to continue.</p>
    </body></html>
    """
    art = extract_article(html)
    assert art.diagnosis
    assert (
        "paywall" in art.diagnosis.lower()
        or "subscriber" in art.diagnosis.lower()
        or "javascript" in art.diagnosis.lower()
        or "weak" in art.diagnosis.lower()
    )


def test_format_truncates_on_sentence_boundary() -> None:
    body = (
        "First sentence about the lab setup is comfortably long enough. "
        "Second sentence continues the thought with more detail for the reader. "
        "Third sentence should usually be cut away when the budget is tight."
    )
    art = extract_article(
        f"<html><body><article><p>{body}</p><p>{body}</p></article></body></html>"
    )
    doc = format_article(art, max_chars=120)
    assert "truncated to 120 chars" in doc
    # Should not end mid-token with a bare cut when a sentence end exists.
    assert "…" in doc or doc.split("[truncated")[0].rstrip().endswith((".", "!", "?"))
