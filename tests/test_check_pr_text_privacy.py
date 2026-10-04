"""The PR and issue text check, tested on what it must catch and what it must leave alone.

`scripts/check_pr_text_privacy.py` exists because a pull request description once carried a
local Windows path with the PC username in it, and nothing read PR text. A check like that
fails in two directions, and both are tested here: a miss leaks, and a false alarm teaches
everyone to ignore it. The third property is the one a log reader depends on: the output
names a category and a place and never the matched text.

Every fixture is synthetic. Anything shaped like a real credential, phone number, mailbox or
home directory is assembled from parts at test time, so no secret scanner and no
`tests/test_no_personal_data.py` rule sees it in the source, and nothing here belongs to a
person. The names, numbers and keys are filler made up for this file.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_pr_text_privacy.py"


def _load():
    name = "check_pr_text_privacy"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


CHECK = _load()

# A made-up account name. Not anyone's, and not a placeholder word either.
FAKE = "zorblax"
# Random-looking filler. Digits and mixed case, so it clears the "is this a stand-in"
# guards the way a real value would, and belongs to no account.
BODY36 = "q7W2e9R4t1Y6u3I8o5P0a2S7d4F9g1H6j3K8"[:36]
BODY48 = "m4N8b2V6c0X3z7L1k5J9h2G4f8D3s6A0p1O7i5U9y2T4r8E6"
HEX32 = "9f3a1c7e5b2d4a60c8e1f7b3d5a92c4e"


def cats(text: str, names: str | None = None) -> set[str]:
    matcher, _ = CHECK.parse_usernames(names)
    return {hit.category for hit in CHECK.scan_text(text, matcher)}


def win(name: str, tail: str = "Documents\\notes.txt", sep: str = "\\") -> str:
    return "C:" + sep + "Users" + sep + name + sep + tail


# --------------------------------------------------------------------------- local paths


@pytest.mark.parametrize(
    "text",
    [
        win(FAKE),
        win(FAKE, "proj", "/"),
        "c:\\\\Users\\\\" + FAKE + "\\\\x",  # the form a JSON string leaves behind
        "/Users/" + FAKE + "/code/app.py",
        "/home/" + FAKE + "/.config/app",
        "PS " + "C:\\Users\\" + FAKE + ">",
        "file:///C:/Users/" + FAKE + "/Desktop/a.png",
        '  File "/home/' + FAKE + '/venv/lib/x.py", line 3',
        "```\n" + win(FAKE) + "\n```",
        "log: " + win(FAKE.upper()),
    ],
)
def test_a_home_directory_path_is_caught(text: str) -> None:
    assert CHECK.CATEGORY_PATH in cats(text)


@pytest.mark.parametrize(
    "text",
    [
        "C:\\Users\\<name>\\Documents",
        "C:/Users/you/proj",
        "C:\\Users\\username\\x",
        "C:\\Users\\YourName\\Desktop",
        "C:\\Users\\your-name\\Desktop",
        "C:\\Users\\%USERNAME%\\Desktop",
        "/Users/<name>/code",
        "/home/$USER/code",
        "/home/{user}/code",
        "/home/user/code",
        "C:\\Users\\Public\\Documents",
        "C:\\Users\\runneradmin\\AppData",
        "/home/runner/work/repo/repo",
        "C:\\Users\\...\\x",
        "https://example.org/home/page/index.html",
        "src/Users/models.py and docs/home/readme.md",
        "the C:\\Users folder holds one directory per account",
    ],
)
def test_placeholders_and_generic_accounts_are_not_paths_to_a_person(text: str) -> None:
    assert CHECK.CATEGORY_PATH not in cats(text)


def test_a_placeholder_path_inside_a_code_fence_is_fine() -> None:
    text = "Repro:\n```powershell\ncd C:\\Users\\<name>\\Documents\\Arelis\n```\n"
    assert cats(text) == set()


def test_a_real_looking_path_inside_a_code_fence_is_still_caught() -> None:
    text = "Repro:\n```powershell\ncd " + win(FAKE) + "\n```\n"
    assert cats(text) == {CHECK.CATEGORY_PATH}


# ----------------------------------------------------------------------------- username


def test_a_listed_username_is_caught_case_insensitively_as_a_whole_word() -> None:
    assert cats("saw " + FAKE.upper() + " in the log", names=FAKE) == {CHECK.CATEGORY_USERNAME}
    assert cats("path " + FAKE + "_laptop", names=FAKE) == {CHECK.CATEGORY_USERNAME}


def test_a_listed_username_inside_a_longer_word_is_not_a_hit() -> None:
    assert cats(FAKE + "ian and un" + FAKE, names=FAKE) == set()


def test_the_username_check_works_when_the_list_is_absent() -> None:
    assert cats("text mentioning " + FAKE, names=None) == set()
    assert cats("text mentioning " + FAKE, names="") == set()


def test_several_usernames_may_be_listed_and_short_ones_are_ignored() -> None:
    names = " one" + FAKE + " , " + FAKE + "\nab"
    matcher, ignored = CHECK.parse_usernames(names)
    assert matcher is not None
    assert ignored == 1
    assert matcher.search("hi " + FAKE)
    assert not matcher.search("a and b and ab")


def test_only_short_usernames_means_no_matcher_at_all() -> None:
    matcher, ignored = CHECK.parse_usernames("ab, c")
    assert matcher is None
    assert ignored == 2


# ------------------------------------------------------------------------------- emails


def _mail(local: str, domain: str) -> str:
    return local + "@" + domain


@pytest.mark.parametrize(
    "text",
    [
        _mail(FAKE, "widgets-corp.net"),
        "write to " + _mail(FAKE + ".smith", "acme-widgets.co.uk") + " please",
        _mail(FAKE, "g" + "mail.com"),
        _mail(FAKE + "+tag", "out" + "look.com"),
        "```\ncontact: " + _mail(FAKE, "widgets-corp.net") + "\n```",
        "<" + _mail(FAKE, "widgets-corp.net") + ">",
    ],
)
def test_an_email_address_is_caught(text: str) -> None:
    assert CHECK.CATEGORY_EMAIL in cats(text)


@pytest.mark.parametrize(
    "text",
    [
        "you@example.com",
        "a@sub.example.org",
        "x@host.test",
        "x@host.invalid",
        "12345+" + FAKE + "@users.noreply.github.com",
        "noreply@github.com",
        "git@github.com:org/repo.git",
        "uses: actions/checkout@v7",
        "pip install pkg@1.2.3",
        "image@2x.png",
        "ping @maintainer and @team-name about it",
        "user@host",
    ],
)
def test_placeholder_and_look_alike_emails_are_left_alone(text: str) -> None:
    assert CHECK.CATEGORY_EMAIL not in cats(text)


# ------------------------------------------------------------------------------- phones

AREA, EXCH, LINE = "303", "456", "7890"  # a made-up number that fits the numbering plan


@pytest.mark.parametrize(
    "text",
    [
        f"({AREA}) {EXCH}-{LINE}",
        f"{AREA}-{EXCH}-{LINE}",
        f"{AREA}.{EXCH}.{LINE}",
        f"tel {AREA} {EXCH} {LINE}",
        f"+1 {AREA} {EXCH} {LINE}",
        f"+1-{AREA}-{EXCH}-{LINE}",
        f"1-{AREA}-{EXCH}-{LINE}",
        f"call me on {AREA}{EXCH}{LINE}",
        f"phone: {AREA}{EXCH}{LINE}",
        "+44 20 7946 0958",
        "+49 30 12345678",
        "+81-3-1234-5678",
        "+44 (0)20 7946 0958",
        "+442079460958",
    ],
)
def test_a_phone_number_is_caught(text: str) -> None:
    assert CHECK.CATEGORY_PHONE in cats(text)


@pytest.mark.parametrize(
    "text",
    [
        "555-555-0123",
        "(555) 123-4567",
        "5555550123",
        "(212) 555-0142",
        "version 2.345.6789 shipped",
        "Python 3.11.9 and 3.14.0",
        "ruff==0.16.9 mypy==2.3.1",
        "commit 3034567890abcdef1234567890abcdef12345678",
        "sha256:dd17e95a7c71bce75e8108113438ba7c4a086b3bcad4f57a8c09b7af3d753c2d",
        "2026-10-03 and 2026-10-03T23:08:00-04:00",
        f"fixes #{AREA}{EXCH}{LINE} and #4567",
        "https://example.org/issues/" + AREA + "-" + EXCH + "-" + LINE,
        "comment id issuecomment-" + AREA + EXCH + LINE,
        "run " + AREA + EXCH + LINE + " finished",
        "unix time 1700000000",
        "host 192.168.100.1234",
        "+12000 -30000 lines changed",
        "diff +2000 30000",
        "contrast 5.85:1 on #060a20",
        "counts " + " ".join(["200", "300", "4000"]) + " seen",
    ],
)
def test_versions_hashes_dates_ids_and_fiction_numbers_are_not_phones(text: str) -> None:
    assert CHECK.CATEGORY_PHONE not in cats(text)


# ----------------------------------------------------------------------- tokens and keys


def _gh(kind: str) -> str:
    return "gh" + kind + "_" + BODY36


def _cases(*pairs: tuple[str, str]):
    """Parameters with readable ids, so a failing run names the case and never prints a value."""
    return [pytest.param(value, id=name) for name, value in pairs]


TOKEN_CASES = _cases(
    ("ghp", _gh("p")),
    ("gho", _gh("o")),
    ("ghs", _gh("s")),
    ("ghu", _gh("u")),
    ("ghp-in-sentence", "token " + _gh("p") + " leaked"),
    ("fine-grained-pat", "github_" + "pat_" + BODY48),
    ("sk-legacy", "sk" + "-" + BODY48),
    ("sk-proj", "sk" + "-proj-" + BODY48 + "_" + BODY36),
    ("bearer-header", "Authorization: Bearer " + BODY36),
    ("bearer-jwt", "bearer " + "eyJ" + "hbGciOiJI.eyJzdWIiOi" + "xMjM0NTY3.SflKxwRJSMeKKF2QT4"),
    ("aws-akia", "AK" + "IA" + "7Q2W9E4R1T6Y3U8I"),
    ("aws-asia", "AS" + "IA" + "7Q2W9E4R1T6Y3U8I"),
    ("slack-xoxb", "xo" + "xb-" + "1234567890-" + BODY36[:16]),
    ("slack-xoxp", "xo" + "xp-" + "1234567890-" + BODY36[:16]),
    ("labeled-hex", "API_KEY=" + HEX32),
    ("labeled-quoted", 'token: "' + BODY48 + '"'),
    ("labeled-export", "export OPENAI_API_KEY=" + BODY48),
    ("labeled-spaced", "client_secret = " + BODY36 + BODY36[:6]),
    (
        "bare-jwt",
        "ey" + "J" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
    ),
    ("pem-rsa", "-----BEGIN " + "RSA PRIVATE" + " KEY-----"),
    ("pem-plain", "-----BEGIN " + "PRIVATE" + " KEY-----"),
)


@pytest.mark.parametrize("text", TOKEN_CASES)
def test_a_token_or_key_is_caught(text: str) -> None:
    assert CHECK.CATEGORY_SECRET in cats(text)


NOT_SECRET_CASES = _cases(
    ("ghp-all-x", "gh" + "p_" + "x" * 36),
    ("ghp-all-X-short", "gh" + "p_" + "X" * 30),
    ("ghp-angle-placeholder", "gh" + "p_<your token here>"),
    ("sk-hyphenated-words", "sk" + "-learn-pipeline-transformers"),
    ("hyphenated-prose", "the task-force ran a risk-assessment-for-long-wording"),
    ("bearer-angle", "Authorization: Bearer <token>"),
    ("bearer-env", "Authorization: Bearer $TOKEN"),
    ("bearer-expression", "Authorization: Bearer ${{ secrets.WEBHOOK_KEY }}"),
    ("bearer-prose", "Bearer tokens are sent in a header"),
    ("bearer-prose-long", "Bearer authentication is used here"),
    ("aws-documented-example", "AK" + "IA" + "IOSFODNN7" + "EXAMPLE"),
    ("slack-all-x", "xo" + "xb-" + "x" * 20),
    ("labeled-all-x", "API_KEY=" + "x" * 40),
    ("labeled-short", "token: abc"),
    ("labeled-short-password", "password: hunter2"),
    ("labeled-zeros", "secret=" + "0" * 40),
    ("unlabeled-commit", "commit=" + "3f2a9c7e1b" * 4),
    ("sha256-line", "sha256: " + HEX32 + HEX32),
    ("rev-parse-prose", "git rev-parse HEAD gave " + "3f2a9c7e1b" * 4),
    ("css-colors", "color #9088a8 on #060a20"),
    ("token-name-only", "GITHUB_TOKEN is set by Actions, not stored"),
)


@pytest.mark.parametrize("text", NOT_SECRET_CASES)
def test_placeholders_hashes_and_ordinary_words_are_not_secrets(text: str) -> None:
    assert CHECK.CATEGORY_SECRET not in cats(text)


# ----------------------------------------------------------------------- street address


@pytest.mark.parametrize(
    "text",
    [
        "123 Main St",
        "123 Main Street, Springfield, IL 62701",
        "742 Evergreen Terrace",
        "4500 W. Elm Blvd, Suite 200",
        "88 N Maple Dr Apt 4B",
        "12 5th Ave",
        "77 OAK LANE",
        "I live at 9 Cedar Ct now",
        "send it to 15 Old Mill Road, Metropolis",
        "PO Box 1234",
        "P.O. Box 77",
        "```\nship to: 31 Birch Pl\n```",
    ],
)
def test_a_street_address_is_caught(text: str) -> None:
    assert CHECK.CATEGORY_ADDRESS in cats(text)


@pytest.mark.parametrize(
    "text",
    [
        "Added 2 Google Drive folders to the picker",
        "Windows 11 Dev Drive support",
        "Replaced 3 Hard Drive checks",
        "Step 3 Run the tests",
        "Fixes 3 failing tests",
        "Python 3.11 Dr Who is not a street",
        "tests/test_x.py:42 Main Street",
        "see #12 Main Street",
        "version v2 Main St",
        "Drive and Street are words",
        "main street shops opened 3 days ago",
        "5 passed in 12.34s",
    ],
)
def test_prose_and_product_names_are_not_street_addresses(text: str) -> None:
    assert CHECK.CATEGORY_ADDRESS not in cats(text)


# ----------------------------------------------------------------------- ordinary prose

NORMAL_PR_BODY = """\
## What this changes
- Adds a selectable theme. `arelis/ui/theme_tokens.py`, `tests/test_night_theme.py`.
- Contrast measured: `#9088a8` is 5.85:1 on `#060a20`.

## Testing
- Before the change: `tests/test_night_theme.py` -> **5 failed**.
- After: **5 passed** (10 total). ruff==0.16.9, Python 3.11 and 3.14.
- Related: #68, #66. Merged as 2c6eb31f in 2026-10-03.
- Placeholder repro: `cd C:\\Users\\<name>\\Documents\\Arelis` or `/home/<name>/Arelis`.
- Contact the maintainer in Discussions. Mail goes to you@example.com in the docs.
"""


def test_a_normal_pull_request_body_has_no_findings() -> None:
    assert cats(NORMAL_PR_BODY) == set()


def test_empty_and_blank_text_has_no_findings() -> None:
    assert cats("") == set()
    assert cats("\n\n   \n") == set()


# ------------------------------------------------------------ the output never has values

LEAKY = "\n".join(
    [
        "path " + win(FAKE),
        "name " + FAKE,
        "mail " + _mail(FAKE, "widgets-corp.net"),
        f"phone ({AREA}) {EXCH}-{LINE}",
        "key " + _gh("p"),
        "home 742 Evergreen Terrace",
    ]
)
SECRET_VALUES = [
    FAKE,
    win(FAKE),
    _mail(FAKE, "widgets-corp.net"),
    f"({AREA}) {EXCH}-{LINE}",
    EXCH,
    BODY36,
    "Evergreen",
]


def test_every_category_is_reported_by_name_and_place(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIVACY_CHECK_USERNAMES", FAKE)
    monkeypatch.setenv("LEAKY_BODY", LEAKY)
    code = CHECK.main(["--env-text", "PR body=LEAKY_BODY"])
    out = capsys.readouterr().out
    assert code == 1
    for category in (
        CHECK.CATEGORY_PATH,
        CHECK.CATEGORY_USERNAME,
        CHECK.CATEGORY_EMAIL,
        CHECK.CATEGORY_PHONE,
        CHECK.CATEGORY_SECRET,
        CHECK.CATEGORY_ADDRESS,
    ):
        assert f"{category} found in PR body" in out


def test_output_and_errors_never_contain_a_matched_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("PRIVACY_CHECK_USERNAMES", FAKE)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("LEAKY_BODY", LEAKY)
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"pull_request": {"title": "t " + FAKE, "body": LEAKY}}), encoding="utf-8"
    )
    code = CHECK.main(
        ["--event-file", str(event), "--event-name", "pull_request",
         "--env-text", "issue comment=LEAKY_BODY"]
    )  # fmt: skip
    captured = capsys.readouterr()
    everything = captured.out + captured.err
    assert code == 1
    for value in SECRET_VALUES:
        assert value not in everything
        assert value.lower() not in everything.lower()
    assert "::error title=PR text privacy::" in everything


def test_a_broken_input_file_does_not_echo_its_contents(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    broken = tmp_path / "event.json"
    broken.write_text('{"pull_request": {"body": "' + _gh("p") + " " + win(FAKE), encoding="utf-8")
    code = CHECK.main(["--event-file", str(broken), "--event-name", "pull_request"])
    captured = capsys.readouterr()
    assert code == 2
    assert BODY36 not in captured.out + captured.err
    assert FAKE not in captured.out + captured.err


def test_a_clean_run_exits_zero_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRIVACY_CHECK_USERNAMES", raising=False)
    monkeypatch.setenv("BODY", NORMAL_PR_BODY)
    assert CHECK.main(["--env-text", "PR body=BODY"]) == 0
    out = capsys.readouterr().out
    assert "passed" in out
    assert "PC username check skipped" in out


def test_the_username_list_is_never_printed_even_when_it_is_the_only_hit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIVACY_CHECK_USERNAMES", FAKE + ",ab")
    monkeypatch.setenv("BODY", "hello " + FAKE)
    assert CHECK.main(["--env-text", "PR title=BODY"]) == 1
    captured = capsys.readouterr()
    assert FAKE not in captured.out + captured.err
    assert "PC username found in PR title (line 1)" in captured.out


def test_the_report_is_capped(capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    monkeypatch.setenv("BODY", "\n".join(_mail(FAKE, "widgets-corp.net") for _ in range(80)))
    assert CHECK.main(["--env-text", "PR body=BODY"]) == 1
    out = capsys.readouterr().out
    assert "and 30 more" in out


# ----------------------------------------------------------------------- reading input


def test_an_empty_run_is_an_error_not_a_pass(capsys: pytest.CaptureFixture[str]) -> None:
    assert CHECK.main([]) == 2
    assert "no text to scan" in capsys.readouterr().err


def test_an_unknown_event_is_an_error_not_a_pass(tmp_path: Path) -> None:
    event = tmp_path / "e.json"
    event.write_text("{}", encoding="utf-8")
    assert CHECK.main(["--event-file", str(event), "--event-name", "push"]) == 2


def test_a_pull_request_event_scans_title_and_body() -> None:
    event = {"pull_request": {"title": "ok", "body": "see " + win(FAKE)}}
    items = CHECK.items_from_event("pull_request", event)
    assert [i.location for i in items] == ["PR title", "PR body"]
    found = CHECK.scan_items(items)
    assert [(loc, h.category) for loc, h in found] == [("PR body", CHECK.CATEGORY_PATH)]


def test_an_issue_event_scans_title_and_body() -> None:
    event = {"issue": {"title": "bug " + _mail(FAKE, "widgets-corp.net"), "body": None}}
    found = CHECK.scan_items(CHECK.items_from_event("issues", event))
    assert [(loc, h.category) for loc, h in found] == [("issue title", CHECK.CATEGORY_EMAIL)]


def test_a_comment_on_a_pr_is_named_differently_from_one_on_an_issue() -> None:
    on_pr = {"issue": {"pull_request": {"url": "x"}}, "comment": {"id": 42, "body": "b"}}
    on_issue = {"issue": {}, "comment": {"id": 43, "body": "b"}}
    assert CHECK.items_from_event("issue_comment", on_pr)[0].location == "PR comment 42"
    assert CHECK.items_from_event("issue_comment", on_issue)[0].location == "issue comment 43"


def test_review_comment_and_review_events_are_handled() -> None:
    comment = {"comment": {"id": 7, "body": "x"}}
    review = {"review": {"id": 8, "body": "y"}}
    assert CHECK.items_from_event("pull_request_review_comment", comment)[0].location == (
        "PR review comment 7"
    )
    assert CHECK.items_from_event("pull_request_review", review)[0].location == "PR review 8"


def test_a_comment_id_that_is_not_a_number_is_not_echoed() -> None:
    event = {"issue": {}, "comment": {"id": "see " + win(FAKE), "body": "b"}}
    location = CHECK.items_from_event("issue_comment", event)[0].location
    assert location == "issue comment"


PAGE_ONE = [{"id": 1, "body": "fine"}, {"id": 2, "body": "mail " + _mail(FAKE, "widgets-corp.net")}]
PAGE_TWO = [{"id": 3, "body": None}, {"id": 4, "body": "path " + win(FAKE)}]


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps(PAGE_ONE) + json.dumps(PAGE_TWO),  # gh api --paginate: arrays back to back
        json.dumps(PAGE_ONE, indent=2) + "\n" + json.dumps(PAGE_TWO, indent=2),
        "\n".join(json.dumps(entry) for entry in PAGE_ONE + PAGE_TWO),  # --jq '.[]'
        json.dumps(PAGE_ONE) + "\n" + json.dumps(PAGE_TWO),
    ],
    ids=["arrays-back-to-back", "pretty-printed", "one-object-per-line", "arrays-per-line"],
)
def test_saved_api_pages_are_read_in_every_shape_gh_writes(raw: str, tmp_path: Path) -> None:
    saved = tmp_path / "comments.json"
    saved.write_text(raw, encoding="utf-8")
    items = CHECK.items_from_stream("PR comment", saved)
    found = CHECK.scan_items(items)
    assert [(loc, h.category) for loc, h in found] == [
        ("PR comment 2", CHECK.CATEGORY_EMAIL),
        ("PR comment 4", CHECK.CATEGORY_PATH),
    ]


def test_an_empty_comments_file_is_a_clean_scan_when_the_event_has_text(tmp_path: Path) -> None:
    empty = tmp_path / "c.json"
    empty.write_text("", encoding="utf-8")
    event = tmp_path / "e.json"
    event.write_text(json.dumps({"pull_request": {"title": "t", "body": "b"}}), encoding="utf-8")
    code = CHECK.main(
        ["--event-file", str(event), "--event-name", "pull_request", "--stream", f"PR comment={empty}"]
    )
    assert code == 0


def test_a_json_file_of_labelled_text_is_scanned(tmp_path: Path) -> None:
    source = tmp_path / "in.json"
    source.write_text(
        json.dumps([{"location": "draft", "text": "ok"}, {"location": "note", "text": win(FAKE)}]),
        encoding="utf-8",
    )
    found = CHECK.scan_items(CHECK.items_from_json_file(source))
    assert [(loc, h.category) for loc, h in found] == [("note", CHECK.CATEGORY_PATH)]


# ------------------------------------------------------------------- as a real process


def test_the_script_runs_as_a_process_and_its_exit_code_is_the_verdict(tmp_path: Path) -> None:
    event = tmp_path / "event.json"
    env = {"PATH": "/usr/bin:/bin", "SYSTEMROOT": "C:\\Windows", "BODY": LEAKY}
    event.write_text(json.dumps({"pull_request": {"title": "t", "body": LEAKY}}), encoding="utf-8")
    bad = subprocess.run(
        [sys.executable, str(SCRIPT), "--event-file", str(event), "--event-name", "pull_request"],
        capture_output=True, text=True, env=env, check=False,
    )  # fmt: skip
    assert bad.returncode == 1
    for value in SECRET_VALUES:
        assert value not in bad.stdout + bad.stderr

    event.write_text(json.dumps({"pull_request": {"title": "t", "body": "fine"}}), encoding="utf-8")
    good = subprocess.run(
        [sys.executable, str(SCRIPT), "--event-file", str(event), "--event-name", "pull_request"],
        capture_output=True, text=True, env=env, check=False,
    )  # fmt: skip
    assert good.returncode == 0


# ----------------------------------------------------------------------- the structure


def test_all_six_categories_have_a_detector() -> None:
    names = [category for category, _ in CHECK.DETECTORS]
    assert sorted(names) == sorted(
        [
            CHECK.CATEGORY_PATH,
            CHECK.CATEGORY_USERNAME,
            CHECK.CATEGORY_EMAIL,
            CHECK.CATEGORY_PHONE,
            CHECK.CATEGORY_SECRET,
            CHECK.CATEGORY_ADDRESS,
        ]
    )
