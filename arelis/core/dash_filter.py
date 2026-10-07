"""Strip em/en dash habits from assistant prose (streaming-safe).

Model replies, SMS/email drafts, and other user-facing text share this. Fenced
code, inline code, and URLs stay byte-identical. Number ranges keep their en
dash. Pure Python, no Qt.
"""

from __future__ import annotations

_DASHES = "\u2014\u2015\u2013"
_EN = "\u2013"
_OPEN = ",;:([{\"'\u201c\u2018"
_OPENERS = "([{\"'\u201c\u2018"
_CLOSE = ",.;:!?)]}\"'\u201d\u2019"
_QUOTE_OPEN = "'\"\u201c\u2018"


def _cjk(ch: str) -> bool:
    return bool(ch) and ("\u3000" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef")


class DashFilter:
    """Character state machine. feed() may hold a short unresolved tail."""

    def __init__(self) -> None:
        self.replaced = 0
        self._pend = ""
        self._prev = ""
        self._line_blank = True
        self._bt = 0
        self._bt_at_line = False
        self._fence = False
        self._inline = False
        self._url = False
        self._url_buf = ""

    def feed(self, chunk: str) -> str:
        out: list[str] = []
        for ch in chunk:
            self._step(ch, out)
        return "".join(out)

    def flush(self) -> str:
        out: list[str] = []
        self._resolve("", out)
        self._url = False
        self._url_buf = ""
        return "".join(out)

    def _emit(self, text: str, out: list[str]) -> None:
        if not text:
            return
        out.append(text)
        for ch in text:
            if ch == "\n":
                self._line_blank = True
                self._prev = ""
            elif ch not in " \t":
                self._prev = ch
                self._line_blank = False

    def _resolve(self, nxt: str, out: list[str]) -> None:
        pend, self._pend = self._pend, ""
        if not pend:
            return
        i = 0
        while i < len(pend) and pend[i] in " \t":
            i += 1
        pre = pend[:i]
        j = i
        while j < len(pend) and pend[j] in _DASHES:
            j += 1
        dashes, post = pend[i:j], pend[j:]
        if not dashes:
            self._emit(pend, out)
            return
        prev = self._prev
        en_only = all(d == _EN for d in dashes)
        tight = not pre and not post
        # Digit ranges keep one en dash (owner: 1990-2000 / 5-10 stay).
        if en_only and prev.isdigit() and nxt.isdigit():
            self._emit(pre + _EN + post, out)
            return
        self.replaced += 1
        if _cjk(prev) or _cjk(nxt):
            self._emit("\uff0c", out)
        elif (prev == "" and self._line_blank) or prev == "":
            # Line-start dashes become a markdown bullet; drop held indent.
            if nxt in ("", "\n", "|"):
                self._emit("-" + post, out)
            else:
                self._emit("- ", out)
        elif prev == "|" or nxt == "|":
            self._emit(pre + "-" + post, out)
        elif tight and en_only:
            self._emit("-", out)
        elif nxt in ("", "\n"):
            self._emit("", out)
        elif (not tight) and nxt in _QUOTE_OPEN:
            # Spaced dash then ' " or curly openers: those quotes are opening,
            # not closing punctuation. Tight word—" / —' can still drop.
            if prev in _OPEN:
                self._emit("" if prev in _OPENERS else " ", out)
            else:
                self._emit(", ", out)
        elif prev in _OPEN or nxt in _CLOSE:
            self._emit("" if (nxt in _CLOSE or prev in _OPENERS) else " ", out)
        else:
            self._emit(", ", out)

    def _url_start(self, ch: str) -> bool:
        """Detect http:// / https:// / www. across the last few emitted chars."""
        buf = (self._url_buf + ch).lower()
        if len(buf) > 8:
            buf = buf[-8:]
        self._url_buf = buf
        return buf.endswith("http://") or buf.endswith("https://") or buf.endswith("www.")

    def _step(self, ch: str, out: list[str]) -> None:
        if self._bt and ch != "`":
            if self._bt >= 3 and self._bt_at_line:
                self._fence = not self._fence
                self._inline = False
            elif not self._fence:
                self._inline = not self._inline
            self._bt = 0

        if self._url:
            if ch in " \t\n":
                self._url = False
                self._url_buf = ""
            else:
                self._emit(ch, out)
                return

        raw = self._fence or self._inline
        if ch == "`":
            self._resolve(ch, out)
            if self._bt == 0:
                self._bt_at_line = self._line_blank
            self._bt += 1
            self._emit(ch, out)
            return
        if raw:
            self._emit(ch, out)
            if ch == "\n":
                self._inline = False
            return
        if ch == "\n":
            self._resolve(ch, out)
            self._emit(ch, out)
            self._url_buf = ""
            return
        if ch in " \t":
            self._pend += ch
            return
        if ch in _DASHES:
            if (
                self._pend
                and self._pend.rstrip(" \t")
                != self._pend.rstrip(" \t").rstrip(_DASHES)
                and self._pend[-1] in " \t"
            ):
                self._resolve(ch, out)
            self._pend += ch
            return
        self._resolve(ch, out)
        if self._url_start(ch):
            self._url = True
        self._emit(ch, out)


def clean_dashes(text: str) -> str:
    """One-shot: feed the whole string and flush."""
    filt = DashFilter()
    return filt.feed(text) + filt.flush()


def clean_dashes_counted(text: str) -> tuple[str, int]:
    """Like clean_dashes, also returning how many dash runs were replaced."""
    filt = DashFilter()
    out = filt.feed(text) + filt.flush()
    return out, filt.replaced
