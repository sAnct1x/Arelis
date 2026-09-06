"""Unicode math is the one form chat, PDF, Word, CSV, and markdown share."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.mathtext import flatten_latex, tex_to_plain
from arelis.tools.document import DocumentTool
from arelis.ui.markdown import flatten_latex as markdown_flatten
from arelis.ui.markdown import render_markdown
from arelis.workspace import WorkspaceRoots


def test_cas_closed_form_keeps_log_and_frac() -> None:
    out = flatten_latex(r"$$\frac{x^{3}}{6} + 25x\log(x-3) - 75\log(x-3)$$")
    assert "log" in out
    assert r"\log" not in out
    assert r"\frac" not in out
    assert "x³" in out
    assert "$$" not in out


def test_price_stays_a_dollar_and_inline_math_flattens() -> None:
    out = flatten_latex(r"cost is $5 and $\log x$ stays math")
    assert "$5" in out
    assert "log x" in out
    assert r"\log" not in out


def test_integral_delimiters_leave() -> None:
    out = flatten_latex(
        r"The integral of \( x^2 \) is \[\int x^2 \, dx = \frac{x^3}{3} + C\]"
    )
    assert r"\(" not in out
    assert r"\[" not in out
    assert "x²" in out
    assert "∫" in out
    assert "x³" in out
    assert "/3" in out


def test_sqrt_keeps_a_compound_radicand_grouped() -> None:
    assert tex_to_plain(r"\sqrt{x+1}") == "√(x+1)"
    assert tex_to_plain(r"\sqrt{x}") == "√x"
    assert tex_to_plain(r"\sqrt[3]{x}") == "³√x"


def test_nested_frac_and_greek() -> None:
    assert tex_to_plain(r"\frac{1}{1+\frac{1}{x}}") == "1/(1+1/x)"
    assert "α" in tex_to_plain(r"\alpha + \beta")
    assert "β" in tex_to_plain(r"\alpha + \beta")


def test_subscripts_and_limits() -> None:
    out = tex_to_plain(r"\sum_{n=1}^{N} x_n")
    assert "Σ" in out
    assert "xₙ" in out
    assert "_" not in out or "N" in out


def test_code_fence_keeps_tex_source() -> None:
    out = flatten_latex("see\n```\n$\\frac{1}{2}$\n```\ndone")
    assert r"\frac" in out
    assert "```" in out
    assert "1/2" not in out.split("```")[0]


def test_windows_path_is_not_eaten() -> None:
    out = flatten_latex(r"read C:\Users\you\notes.md then \frac{1}{2}")
    assert r"\Users" in out
    assert "1/2" in out
    assert r"\frac" not in out
    assert "C:\\input" in flatten_latex(r"open C:\input next")
    assert "∈" not in flatten_latex(r"open C:\input next")
    assert r"folder\log" in flatten_latex(r"see folder\log then done")


def test_bare_integral_scripts_and_thin_space() -> None:
    out = flatten_latex(r"\int_0^\infty e^{-x}\,dx")
    assert "∫" in out
    assert r"\int" not in out
    assert r"\," not in out
    assert "e⁻ˣ" in out or "e^{-x}" not in out


def test_cas_sympy_latex_flattens() -> None:
    latex = r"\frac{x^{3}}{6} + 25 x \log{\left(x - 3 \right)} - 75 \log{\left(x - 3 \right)}"
    out = flatten_latex("$$" + latex + "$$")
    assert "log" in out
    assert r"\log" not in out
    assert r"\left" not in out
    assert "x³" in out
    assert "6" in out


def test_markdown_reexports_the_same_flattener() -> None:
    src = r"$$\int x\,dx$$"
    assert markdown_flatten(src) == flatten_latex(src)


def test_chat_centers_display_math() -> None:
    html = render_markdown(r"The energy is $$\frac{1}{2}mv^2$$ as usual.")
    assert "text-align:center" in html
    assert "font-style:italic" in html
    assert "½" in html or "1/2" in html
    assert "mv²" in html or "mv^2" in html
    assert r"\frac" not in html
    assert "$$" not in html


def test_inline_math_in_a_sentence() -> None:
    html = render_markdown(r"Force is $F = ma$ on the nose.")
    assert "F = ma" in html
    assert "$" not in html.replace("&#", "")


def test_research_report_flattens_tex(tmp_path) -> None:
    from arelis.research.report import save_report

    path = save_report(
        "# Q\n\nThe root is $$\\sqrt{x+1}$$.\n",
        query="sqrt note",
        output_dir=tmp_path,
    )
    text = path.read_text(encoding="utf-8")
    assert r"\sqrt" not in text
    assert "√(x+1)" in text


def test_chat_bubble_shows_unicode_math(qt_app) -> None:
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.finish_assistant(r"The integral is $$\int x^2 \, dx = \frac{x^3}{3} + C$$")
    text = panel.view.toPlainText()
    assert "∫" in text
    assert "x³" in text
    assert r"\frac" not in text
    assert "$$" not in text


@pytest.fixture
def doc_tool(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    data = tmp_path / "appdata"
    data.mkdir()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    workspace = WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "project", "path": str(root)}]}}
    )
    return DocumentTool(workspace)


@pytest.mark.asyncio
async def test_pdf_word_csv_md_all_flatten_tex(doc_tool) -> None:
    body = (
        "The closed form is\n\n"
        r"$$\frac{x^{3}}{6} + 25x\log(x-3)$$" + "\n\n"
        "and the root is " + r"$\sqrt{x+1}$."
    )

    md = await doc_tool.run(format="md", title="Math", body=body)
    assert md.ok, md.output
    md_text = Path(md.data["abs_path"]).read_text(encoding="utf-8")
    assert r"\frac" not in md_text
    assert "log" in md_text
    assert "x³" in md_text
    assert "√(x+1)" in md_text

    txt = await doc_tool.run(format="txt", title="Math txt", body=body)
    assert txt.ok, txt.output
    txt_text = Path(txt.data["abs_path"]).read_text(encoding="utf-8")
    assert r"\frac" not in txt_text
    assert "√(x+1)" in txt_text

    pdf = await doc_tool.run(format="pdf", title="Math pdf", body=body)
    assert pdf.ok, pdf.output
    from pypdf import PdfReader

    pages = PdfReader(str(Path(pdf.data["abs_path"]))).pages
    pdf_text = "\n".join(page.extract_text() or "" for page in pages)
    assert r"\frac" not in pdf_text
    assert "log" in pdf_text

    docx = await doc_tool.run(format="docx", title="Math docx", body=body)
    assert docx.ok, docx.output
    from docx import Document

    word = Document(str(Path(docx.data["abs_path"])))
    word_text = "\n".join(p.text for p in word.paragraphs)
    assert r"\frac" not in word_text
    assert "log" in word_text
    assert any(run.italic for p in word.paragraphs for run in p.runs)

    csv = await doc_tool.run(
        format="csv",
        title="Math csv",
        rows='[["formula"], ["$$\\\\frac{a}{b}$$"]]',
    )
    assert csv.ok, csv.output
    csv_text = Path(csv.data["abs_path"]).read_text(encoding="utf-8-sig")
    assert r"\frac" not in csv_text
    assert "a/b" in csv_text

    xlsx = await doc_tool.run(
        format="xlsx",
        title="Math xlsx",
        rows='[["formula"], ["$$\\\\sqrt{x+1}$$"]]',
    )
    assert xlsx.ok, xlsx.output
    from openpyxl import load_workbook

    book = load_workbook(Path(xlsx.data["abs_path"]))
    assert book.active["A2"].value == "√(x+1)"

    source = Path(md.data["abs_path"])
    exported = await doc_tool.run(
        format="pdf",
        title="From md",
        from_path=str(source),
    )
    assert exported.ok, exported.output
    from pypdf import PdfReader

    from_text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(str(Path(exported.data["abs_path"]))).pages
    )
    assert r"\frac" not in from_text
    assert "log" in from_text

    table_body = "| a | b |\n| --- | --- |\n| $\\frac{1}{2}$ | ok |\n"
    table_doc = await doc_tool.run(format="docx", title="Table math", body=table_body)
    assert table_doc.ok, table_doc.output
    table_word = Document(str(Path(table_doc.data["abs_path"])))
    cells = [[c.text for c in row.cells] for t in table_word.tables for row in t.rows]
    assert ["1/2", "ok"] in cells
