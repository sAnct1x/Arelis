package app.arelis

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.ParagraphStyle
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextIndent
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.sp

/**
 * Markdown plus unicode math for a finished reply.
 * LinkAnnotation is not in this Compose version, so a link is a string
 * annotation named URL. The bubble opens http and https from that.
 */
data class ReplyInk(
    val text: Long,
    val dim: Long,
    val codeFill: Long,
    val accent: Long,
)

data class ReplyRun(
    val text: String,
    val bold: Boolean = false,
    val italic: Boolean = false,
    val code: Boolean = false,
    val codeBlock: Boolean = false,
    val heading: Int = 0,
    val link: String? = null,
    val quote: Boolean = false,
    val list: Boolean = false,
    val codeFill: Long = 0,
    val linkColor: Long = 0,
    val tone: Long = 0,
)

data class ReplyDoc(val runs: List<ReplyRun>) {
    val visible: String get() = runs.joinToString("") { it.text }
}

private const val SHIELD_L = '\uE000'
private const val SHIELD_R = '\uE001'

private data class Style(
    val bold: Boolean = false,
    val italic: Boolean = false,
    val heading: Int = 0,
    val quote: Boolean = false,
    val list: Boolean = false,
    val link: String? = null,
)

private val headingRe = Regex("""^(#{1,6})[ \t]+(\S.*)$""")
private val quoteRe = Regex("""^>[ \t]?(.*)$""")
private val bulletRe = Regex("""^[-*+][ \t]+(.*)$""")
private val numberRe = Regex("""^(\d{1,9})[.)][ \t]+(.*)$""")
private val linkRe = Regex("""^\[([^\]\n]+)\]\(([^)\s]+)\)""")

fun formatReply(src: String, ink: ReplyInk): ReplyDoc {
    val lines = src.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    val out = ArrayList<ReplyRun>()
    val prose = ArrayList<String>()
    fun appendPart(runs: List<ReplyRun>) {
        if (runs.isEmpty()) return
        if (out.isNotEmpty()) out.add(ReplyRun("\n"))
        out.addAll(runs)
    }
    fun flushProse() {
        if (prose.isEmpty()) return
        val flat = MathText.flatten(prose.joinToString("\n"), shield = true)
        appendPart(parseBlocks(flat, ink))
        prose.clear()
    }
    var i = 0
    while (i < lines.size) {
        if (lines[i].trim().startsWith("```")) {
            flushProse()
            val opener = lines[i]
            val body = ArrayList<String>()
            i += 1
            var closed = false
            while (i < lines.size) {
                if (lines[i].trim().startsWith("```")) {
                    closed = true
                    i += 1
                    break
                }
                body.add(lines[i])
                i += 1
            }
            if (!closed) {
                val raw = ArrayList<String>()
                raw.add(opener)
                raw.addAll(body)
                appendPart(listOf(ReplyRun(raw.joinToString("\n"))))
            } else {
                appendPart(
                    listOf(
                        ReplyRun(
                            text = body.joinToString("\n"),
                            code = true,
                            codeBlock = true,
                            codeFill = ink.codeFill,
                        ),
                    ),
                )
            }
            continue
        }
        prose.add(lines[i])
        i += 1
    }
    flushProse()
    return ReplyDoc(out)
}

fun ReplyDoc.toAnnotatedString(): AnnotatedString = buildAnnotatedString {
    val paragraphs = ArrayList<List<ReplyRun>>()
    var current = ArrayList<ReplyRun>()
    for (run in runs) {
        if (run.text == "\n" && !run.bold && !run.italic && !run.code && run.link == null) {
            paragraphs.add(current)
            current = ArrayList()
        } else {
            current.add(run)
        }
    }
    paragraphs.add(current)
    paragraphs.forEachIndexed { index, paragraph ->
        if (index > 0) append('\n')
        val list = paragraph.any { it.list }
        val quote = paragraph.any { it.quote }
        if (list || quote) {
            pushStyle(
                ParagraphStyle(
                    textIndent = TextIndent(
                        firstLine = 0.sp,
                        restLine = if (list) 18.sp else 12.sp,
                    ),
                ),
            )
        }
        for (run in paragraph) {
            val span = spanFor(run)
            if (run.link != null) {
                pushStringAnnotation("URL", run.link)
                withStyle(span) { append(run.text) }
                pop()
            } else {
                withStyle(span) { append(run.text) }
            }
        }
        if (list || quote) pop()
    }
}

private fun spanFor(run: ReplyRun): SpanStyle {
    val size = when (run.heading) {
        1 -> 22.sp
        2 -> 20.sp
        3 -> 18.sp
        in 4..6 -> 17.sp
        else -> androidx.compose.ui.unit.TextUnit.Unspecified
    }
    val color = when {
        run.link != null && run.linkColor != 0L -> Color(run.linkColor)
        run.tone != 0L -> Color(run.tone)
        else -> null
    }
    return SpanStyle(
        fontWeight = when {
            run.heading > 0 -> FontWeight.Bold
            run.bold -> FontWeight.SemiBold
            else -> null
        },
        fontStyle = if (run.italic) FontStyle.Italic else null,
        fontFamily = if (run.code || run.codeBlock) FontFamily.Monospace else null,
        fontSize = size,
        background = if ((run.code || run.codeBlock) && run.codeFill != 0L) Color(run.codeFill) else Color.Unspecified,
        textDecoration = if (run.link != null) TextDecoration.Underline else null,
        color = color ?: Color.Unspecified,
    )
}

private fun parseBlocks(text: String, ink: ReplyInk): List<ReplyRun> {
    val lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    val out = ArrayList<ReplyRun>()
    var i = 0
    var started = false
    fun sep() {
        if (started) out.add(ReplyRun("\n"))
        started = true
    }
    while (i < lines.size) {
        val line = lines[i]
        val trim = line.trim()
        if (trim.startsWith("```")) {
            val body = ArrayList<String>()
            i += 1
            var closed = false
            while (i < lines.size) {
                if (lines[i].trim().startsWith("```")) {
                    closed = true
                    i += 1
                    break
                }
                body.add(lines[i])
                i += 1
            }
            sep()
            if (!closed) {
                val raw = ArrayList<String>()
                raw.add(line)
                raw.addAll(body)
                out.add(plain(raw.joinToString("\n")))
            } else {
                out.add(
                    ReplyRun(
                        text = body.joinToString("\n"),
                        code = true,
                        codeBlock = true,
                        codeFill = ink.codeFill,
                    ),
                )
            }
            continue
        }
        if (trim.isEmpty()) {
            sep()
            i += 1
            continue
        }
        val literal = unwrapShield(trim)
        if (literal != null && trim == line.trim() && line.trim().length == trim.length) {
            sep()
            out.add(plain(literal))
            i += 1
            continue
        }
        val heading = headingRe.matchEntire(trim)
        if (heading != null) {
            sep()
            val level = heading.groupValues[1].length
            out.addAll(parseInline(heading.groupValues[2], ink, Style(bold = true, heading = level)))
            i += 1
            continue
        }
        val quote = quoteRe.matchEntire(trim)
        if (quote != null) {
            sep()
            out.addAll(parseInline(quote.groupValues[1], ink, Style(quote = true)))
            i += 1
            continue
        }
        val bullet = bulletRe.matchEntire(trim)
        if (bullet != null) {
            sep()
            out.add(ReplyRun("• ", list = true))
            out.addAll(parseInline(bullet.groupValues[1], ink, Style(list = true)))
            i += 1
            continue
        }
        val number = numberRe.matchEntire(trim)
        if (number != null) {
            sep()
            out.add(ReplyRun(number.groupValues[1] + ". ", list = true))
            out.addAll(parseInline(number.groupValues[2], ink, Style(list = true)))
            i += 1
            continue
        }
        sep()
        out.addAll(parseInline(line, ink, Style()))
        i += 1
    }
    return out.filter { it.text.isNotEmpty() }
}

private fun plain(text: String) = ReplyRun(text)

private fun unwrapShield(text: String): String? {
    val t = text.trim()
    if (t.length >= 2 && t.first() == SHIELD_L && t.last() == SHIELD_R && t.indexOf(SHIELD_R) == t.lastIndex) {
        return t.substring(1, t.lastIndex)
    }
    return null
}

private fun parseInline(src: String, ink: ReplyInk, style: Style): List<ReplyRun> {
    val out = ArrayList<ReplyRun>()
    val buf = StringBuilder()
    var i = 0
    fun flush() {
        if (buf.isNotEmpty()) {
            out.add(runOf(buf.toString(), ink, style, code = false))
            buf.clear()
        }
    }
    while (i < src.length) {
        if (src[i] == SHIELD_L) {
            val end = src.indexOf(SHIELD_R, i + 1)
            if (end > i) {
                flush()
                out.add(plain(src.substring(i + 1, end)))
                i = end + 1
                continue
            }
        }
        if (src[i] == '[') {
            val match = linkRe.find(src.substring(i))
            if (match != null && match.range.first == 0) {
                val url = match.groupValues[2]
                if (isHttp(url)) {
                    flush()
                    out.addAll(parseInline(match.groupValues[1], ink, style.copy(link = url)))
                    i += match.value.length
                    continue
                }
            }
        }
        if (src[i] == '`') {
            val end = src.indexOf('`', i + 1)
            if (end > i && '\n' !in src.substring(i + 1, end)) {
                flush()
                out.add(runOf(src.substring(i + 1, end), ink, style.copy(bold = false, italic = false), code = true))
                i = end + 1
                continue
            }
        }
        val marker = markerAt(src, i)
        if (marker != null) {
            val close = findClose(src, i + marker.length, marker)
            if (close >= 0) {
                flush()
                val inner = src.substring(i + marker.length, close)
                out.addAll(parseInline(inner, ink, style.withMarker(marker)))
                i = close + marker.length
                continue
            }
        }
        buf.append(src[i])
        i += 1
    }
    flush()
    return out
}

private fun Style.withMarker(marker: String): Style = when (marker) {
    "***", "___" -> copy(bold = true, italic = true)
    "**", "__" -> copy(bold = true)
    "*", "_" -> copy(italic = true)
    else -> this
}

private fun markerAt(src: String, i: Int): String? {
    val c = src[i]
    if (c != '*' && c != '_') return null
    if (c == '_' && i > 0 && src[i - 1].isLetterOrDigit()) return null
    var n = 0
    while (i + n < src.length && src[i + n] == c && n < 3) n += 1
    if (n == 0) return null
    return c.toString().repeat(n)
}

private fun findClose(src: String, from: Int, marker: String): Int {
    var i = from
    while (i < src.length) {
        if (src[i] == SHIELD_L) {
            val end = src.indexOf(SHIELD_R, i + 1)
            i = if (end < 0) src.length else end + 1
            continue
        }
        if (src.startsWith(marker, i)) {
            if (marker.length == 1 && i + 1 < src.length && src[i + 1] == marker[0]) {
                i += 1
                continue
            }
            if (marker[0] == '_' && i + marker.length < src.length && src[i + marker.length].isLetterOrDigit()) {
                i += 1
                continue
            }
            return i
        }
        i += 1
    }
    return -1
}

private fun isHttp(url: String): Boolean {
    val lower = url.lowercase()
    return lower.startsWith("https://") || lower.startsWith("http://")
}

private fun runOf(text: String, ink: ReplyInk, style: Style, code: Boolean): ReplyRun = ReplyRun(
    text = text,
    bold = style.bold,
    italic = style.italic,
    code = code,
    heading = style.heading,
    link = style.link,
    quote = style.quote,
    list = style.list,
    codeFill = if (code) ink.codeFill else 0L,
    linkColor = if (style.link != null) ink.accent else 0L,
    tone = if (style.quote && style.link == null) ink.dim else 0L,
)
