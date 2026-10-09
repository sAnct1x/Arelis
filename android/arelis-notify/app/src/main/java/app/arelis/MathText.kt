package app.arelis

/**
 * TeX to a readable unicode line. Same rules as the desktop flattener:
 * delimiters, Greek, fractions, scripts, and roots. Code fences stay source.
 */
object MathText {
    private const val SHIELD_L = '\uE000'
    private const val SHIELD_R = '\uE001'

    private val displayDollars = Regex("""\$\$(.+?)\$\$""", RegexOption.DOT_MATCHES_ALL)
    private val displayBrackets = Regex("""\\\[(.+?)\\\]""", RegexOption.DOT_MATCHES_ALL)
    private val inlineParens = Regex("""\\\((.+?)\\\)""", RegexOption.DOT_MATCHES_ALL)
    private val mathSignal = Regex("""[\\^_=<>|*]""")
    private val spacedName = Regex("""\s*[A-Za-z](?:[A-Za-z0-9]|_[A-Za-z0-9]+)*\s*""")
    private val plainMath = Regex("""[\\^_{]|[A-Za-z]""")
    private val fence = Regex("""^```""")
    private val envSplit = Regex("""\\\\""")
    private val simple = Regex(
        "^[A-Za-z0-9" +
            "\u03b1-\u03c9\u0391-\u03a9" +
            "\u03c0\u221e\u2202\u2207\u2113\u210f" +
            "\u00b9\u00b2\u00b3\u2070\u2074-\u2079\u207a-\u207f" +
            "\u2080-\u208e\u2090-\u209c\u1d62-\u1d65\u2c7c" +
            "]+$",
    )

    private val sup = mapOf(
        "0" to "⁰", "1" to "¹", "2" to "²", "3" to "³", "4" to "⁴",
        "5" to "⁵", "6" to "⁶", "7" to "⁷", "8" to "⁸", "9" to "⁹",
        "+" to "⁺", "-" to "⁻", "=" to "⁼", "(" to "⁽", ")" to "⁾",
        "n" to "ⁿ", "i" to "ⁱ",
        "a" to "\u1d43", "b" to "\u1d47", "c" to "\u1d9c", "d" to "\u1d48",
        "e" to "\u1d49", "f" to "\u1da0", "g" to "\u1d4d", "h" to "\u02b0",
        "k" to "\u1d4f", "l" to "\u02e1", "m" to "\u1d50", "o" to "\u1d52",
        "p" to "\u1d56", "r" to "\u02b3", "s" to "\u02e2", "t" to "\u1d57",
        "u" to "\u1d58", "v" to "\u1d5b", "w" to "\u02b7", "x" to "\u02e3",
        "y" to "\u02b8", "z" to "\u1dbb",
    )
    private val sub = mapOf(
        "0" to "\u2080", "1" to "\u2081", "2" to "\u2082", "3" to "\u2083",
        "4" to "\u2084", "5" to "\u2085", "6" to "\u2086", "7" to "\u2087",
        "8" to "\u2088", "9" to "\u2089", "+" to "\u208a", "-" to "\u208b",
        "=" to "\u208c", "(" to "\u208d", ")" to "\u208e",
        "a" to "\u2090", "e" to "\u2091", "o" to "\u2092", "x" to "\u2093",
        "h" to "\u2095", "k" to "\u2096", "l" to "\u2097", "m" to "\u2098",
        "n" to "\u2099", "p" to "\u209a", "s" to "\u209b", "t" to "\u209c",
        "i" to "\u1d62", "j" to "\u2c7c", "r" to "\u1d63", "u" to "\u1d64",
        "v" to "\u1d65",
    )
    private val symbols = mapOf(
        "alpha" to "α", "beta" to "β", "gamma" to "γ", "delta" to "δ",
        "epsilon" to "ε", "varepsilon" to "ε", "zeta" to "ζ", "eta" to "η",
        "theta" to "θ", "vartheta" to "ϑ", "iota" to "ι", "kappa" to "κ",
        "lambda" to "λ", "mu" to "μ", "nu" to "ν", "xi" to "ξ", "pi" to "π",
        "varpi" to "ϖ", "rho" to "ρ", "varrho" to "ϱ", "sigma" to "σ",
        "varsigma" to "ς", "tau" to "τ", "upsilon" to "υ", "phi" to "φ",
        "varphi" to "ϕ", "chi" to "χ", "psi" to "ψ", "omega" to "ω",
        "Gamma" to "Γ", "Delta" to "Δ", "Theta" to "Θ", "Lambda" to "Λ",
        "Xi" to "Ξ", "Pi" to "Π", "Sigma" to "Σ", "Upsilon" to "Υ",
        "Phi" to "Φ", "Psi" to "Ψ", "Omega" to "Ω",
        "infty" to "∞", "partial" to "∂", "nabla" to "∇", "emptyset" to "∅",
        "cdot" to "·", "times" to "×", "div" to "÷", "pm" to "±", "mp" to "∓",
        "leq" to "≤", "le" to "≤", "geq" to "≥", "ge" to "≥", "neq" to "≠",
        "ne" to "≠", "approx" to "≈", "equiv" to "≡", "sim" to "∼",
        "propto" to "∝", "in" to "∈", "notin" to "∉", "subset" to "⊂",
        "subseteq" to "⊆", "forall" to "∀", "exists" to "∃", "neg" to "¬",
        "land" to "∧", "lor" to "∨", "to" to "→", "rightarrow" to "→",
        "leftarrow" to "←", "Rightarrow" to "⇒", "Leftarrow" to "⇐",
        "mapsto" to "↦", "circ" to "∘", "bullet" to "•", "ldots" to "…",
        "cdots" to "⋯", "dots" to "…", "hbar" to "ℏ", "ell" to "ℓ",
        "degree" to "°", "Re" to "Re", "Im" to "Im", "int" to "∫",
        "iint" to "∬", "iiint" to "∭", "sum" to "Σ", "prod" to "Π",
        "quad" to "  ", "qquad" to "    ", "cup" to "∪", "cap" to "∩",
        "langle" to "⟨", "rangle" to "⟩", "implies" to "⇒", "impliedby" to "⇐",
        "iff" to "⇔", "perp" to "⊥", "mid" to "∣", "parallel" to "∥",
        "vert" to "∣", "Vert" to "‖", "|" to "‖", "bmod" to " mod ",
        "angle" to "∠", "ll" to "≪", "gg" to "≫", "supseteq" to "⊇",
        "supset" to "⊃", "varnothing" to "∅", "vdots" to "⋮", "ddots" to "⋱",
        "ni" to "∋", "therefore" to "∴", "because" to "∵", "oplus" to "⊕",
        "otimes" to "⊗", "setminus" to "∖", "cong" to "≅", "simeq" to "≃",
        "leftrightarrow" to "↔", "uparrow" to "↑", "downarrow" to "↓",
        "prime" to "′", "star" to "∗", "triangle" to "△", "square" to "□",
        "aleph" to "ℵ", "nsubseteq" to "⊈", "nsupseteq" to "⊉", "approxeq" to "≊",
    )
    private val functions = setOf(
        "sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "exp", "lim",
        "det", "min", "max", "arg", "arcsin", "arccos", "arctan", "sinh",
        "cosh", "tanh",
    )
    private val noop = setOf(
        "displaystyle", "textstyle", "scriptstyle", "limits", "nolimits",
        "mathstrut", "!",
    )
    private val textCmds = setOf(
        "text", "textrm", "mbox", "mathrm", "operatorname", "mathbf", "mathit",
        "boxed", "mathbb", "mathcal", "mathscr", "mathfrak", "bm", "boldsymbol",
    )
    private val convertText = setOf(
        "mathrm", "operatorname", "mathbf", "mathit", "boxed", "mathbb",
        "mathcal", "mathscr", "mathfrak", "bm", "boldsymbol",
    )
    private val accents = mapOf(
        "hat" to "\u0302", "bar" to "\u0304", "overline" to "\u0305",
        "vec" to "\u20d7", "tilde" to "\u0303", "dot" to "\u0307",
        "ddot" to "\u0308", "underline" to "\u0332",
    )
    private val texCmds: Set<String> = symbols.keys + functions + textCmds + accents.keys + noop + setOf(
        "frac", "dfrac", "tfrac", "cfrac", "sqrt", "binom", "left", "right",
        "begin", "end", ",", ":", ";", "!", " ",
    )
    private val pathBefore = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.:".toSet()
    private val texAfter = "{[_^ \t\n,.;:!)](".toSet()

    fun texToPlain(src: String): String = convert(src.trim(), unknown = "keep").trim()

    fun flatten(text: String, shield: Boolean = false): String {
        if (text.isEmpty()) return text
        val parts = ArrayList<String>()
        for ((kind, chunk) in splitProtected(text)) {
            parts.add(if (kind == "code") chunk else flattenProse(chunk, shield))
        }
        return parts.joinToString("")
    }

    private fun splitProtected(text: String): List<Pair<String, String>> {
        val out = ArrayList<Pair<String, String>>()
        val lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        var i = 0
        val buf = ArrayList<String>()
        fun flushText() {
            if (buf.isNotEmpty()) {
                out.add("text" to buf.joinToString("\n"))
                buf.clear()
            }
        }
        while (i < lines.size) {
            val line = lines[i]
            if (fence.containsMatchIn(line.trim()) && fence.find(line.trim())?.range?.first == 0) {
                flushText()
                val fenceLines = ArrayList<String>()
                fenceLines.add(line)
                i += 1
                while (i < lines.size && !(fence.containsMatchIn(lines[i].trim()) && fence.find(lines[i].trim())?.range?.first == 0)) {
                    fenceLines.add(lines[i])
                    i += 1
                }
                if (i < lines.size) {
                    fenceLines.add(lines[i])
                    i += 1
                }
                out.add("code" to fenceLines.joinToString("\n"))
                continue
            }
            buf.add(line)
            i += 1
        }
        flushText()
        val split = ArrayList<Pair<String, String>>()
        for ((kind, chunk) in out) {
            if (kind == "code") split.add(kind to chunk) else split.addAll(splitInlineCode(chunk))
        }
        return split
    }

    private fun splitInlineCode(text: String): List<Pair<String, String>> {
        val parts = ArrayList<Pair<String, String>>()
        var pos = 0
        while (pos < text.length) {
            val start = text.indexOf('`', pos)
            if (start < 0) {
                if (pos < text.length) parts.add("text" to text.substring(pos))
                break
            }
            if (start > pos) parts.add("text" to text.substring(pos, start))
            val end = text.indexOf('`', start + 1)
            if (end < 0 || '\n' in text.substring(start + 1, end)) {
                parts.add("text" to text.substring(start))
                break
            }
            parts.add("code" to text.substring(start, end + 1))
            pos = end + 1
        }
        return parts
    }

    private fun inlineDollarOk(inner: String): Boolean {
        if (inner.isEmpty() || '\n' in inner) return false
        if (inner[0].isDigit() || inner[0].isWhitespace()) {
            if (mathSignal.containsMatchIn(inner)) return true
            return inner[0].isWhitespace() && spacedName.matchEntire(inner) != null
        }
        return plainMath.containsMatchIn(inner)
    }

    private fun replaceInlineDollars(text: String, shield: Boolean): String {
        val out = StringBuilder()
        var i = 0
        val n = text.length
        while (i < n) {
            if (text[i] != '$') {
                out.append(text[i])
                i += 1
                continue
            }
            if (i + 1 < n && text[i + 1] == '$') {
                out.append('$')
                i += 1
                continue
            }
            val j = text.indexOf('$', i + 1)
            val inner = if (j >= 0) text.substring(i + 1, j) else ""
            val closerOk = j > i + 1 && '\n' !in inner && !(j + 1 < n && text[j + 1] == '$')
            if (closerOk && inlineDollarOk(inner)) {
                out.append(shielded(texToPlain(inner), shield))
                i = j + 1
                continue
            }
            out.append('$')
            i += 1
        }
        return out.toString()
    }

    private fun shielded(body: String, shield: Boolean): String =
        if (shield) "$SHIELD_L$body$SHIELD_R" else body

    private fun flattenProse(text: String, shield: Boolean): String {
        var next = displayDollars.replace(text) { "\n" + shielded(texToPlain(it.groupValues[1]), shield) + "\n" }
        next = displayBrackets.replace(next) { "\n" + shielded(texToPlain(it.groupValues[1]), shield) + "\n" }
        next = inlineParens.replace(next) { shielded(texToPlain(it.groupValues[1]), shield) }
        next = replaceInlineDollars(next, shield)
        if ('\\' in next) next = flattenBare(next)
        return next
    }

    private fun isTexSite(src: String, i: Int): Boolean {
        if (i >= src.length || src[i] != '\\') return false
        if (i > 0 && src[i - 1] in pathBefore) return false
        val (cmd, j) = readCmd(src, i)
        if (cmd !in texCmds) return false
        if (j >= src.length) return true
        if (cmd in setOf(",", ":", ";", "!", " ")) return true
        return src[j] in texAfter
    }

    private fun flattenBare(text: String): String {
        val out = StringBuilder()
        var i = 0
        val n = text.length
        while (i < n) {
            if (text[i] == '\\' && isTexSite(text, i)) {
                val piece = command(text, i, unknown = "keep")
                var built = piece.first
                i = piece.second
                while (i < n && text[i] in "^_") {
                    val mark = text[i]
                    val grp = readGroup(text, i + 1)
                    val table = if (mark == '^') sup else sub
                    built += script(convert(grp.first, unknown = "keep"), table, mark.toString())
                    i = grp.second
                }
                out.append(built)
                continue
            }
            if (i + 1 < n && text[i + 1] == '^' && text[i].isLetterOrDigit()) {
                val grp = readGroup(text, i + 2)
                out.append(text[i])
                out.append(script(convert(grp.first, unknown = "keep"), sup, "^"))
                i = grp.second
                continue
            }
            out.append(text[i])
            i += 1
        }
        return out.toString()
    }

    private fun convert(src: String, unknown: String): String {
        val out = StringBuilder()
        var i = 0
        val n = src.length
        while (i < n) {
            val ch = src[i]
            when (ch) {
                '\\' -> {
                    val piece = command(src, i, unknown)
                    out.append(piece.first)
                    i = piece.second
                }
                '^' -> {
                    val grp = readGroup(src, i + 1)
                    out.append(script(convert(grp.first, unknown), sup, "^"))
                    i = grp.second
                }
                '_' -> {
                    val grp = readGroup(src, i + 1)
                    out.append(script(convert(grp.first, unknown), sub, "_"))
                    i = grp.second
                }
                '{' -> {
                    val grp = readGroup(src, i)
                    out.append(convert(grp.first, unknown))
                    i = grp.second
                }
                '}' -> i += 1
                '&' -> {
                    out.append("  ")
                    i += 1
                }
                else -> {
                    out.append(ch)
                    i += 1
                }
            }
        }
        return out.toString()
    }

    private fun command(src: String, i: Int, unknown: String): Pair<String, Int> {
        val read = readCmd(src, i)
        val cmd = read.first
        var at = read.second
        if (cmd in noop) return "" to at
        if (cmd in setOf(",", ":", ";")) return " " to at
        if (cmd in setOf(" ", "quad", "qquad")) return (symbols[cmd] ?: " ") to at
        if (cmd == "\\") return "; " to at
        if (cmd in setOf("{", "}", "%", "$", "#", "_", "&")) return cmd to at
        if (cmd in textCmds) {
            val grp = readGroup(src, at)
            at = grp.second
            if (cmd in convertText) return convert(grp.first, unknown) to at
            return grp.first to at
        }
        if (cmd in setOf("frac", "dfrac", "tfrac", "cfrac")) {
            val num = readGroup(src, at)
            val den = readGroup(src, num.second)
            val body = paren(convert(num.first, unknown)) + "/" + paren(convert(den.first, unknown))
            return body to den.second
        }
        if (cmd == "sqrt") {
            var root = ""
            var j = skipSpace(src, at)
            if (j < src.length && src[j] == '[') {
                val bracket = readBracket(src, j)
                root = script(convert(bracket.first, unknown), sup, "^")
                j = bracket.second
            }
            val inner = readGroup(src, j)
            return root + "√" + paren(convert(inner.first, unknown)) to inner.second
        }
        if (cmd == "binom") {
            val n = readGroup(src, at)
            val k = readGroup(src, n.second)
            return "C(${convert(n.first, unknown)}, ${convert(k.first, unknown)})" to k.second
        }
        if (cmd in accents) {
            val grp = readGroup(src, at)
            val body = convert(grp.first, unknown)
            return body + accents.getValue(cmd) to grp.second
        }
        if (cmd in setOf("left", "right")) {
            val j = skipSpace(src, at)
            if (j >= src.length) return "" to at
            val delim = src[j]
            if (delim == '.') return "" to j + 1
            if (delim == '\\') {
                val inner = readCmd(src, j)
                val mapped = symbols[inner.first] ?: if (unknown == "strip") inner.first else "\\" + inner.first
                return mapped to inner.second
            }
            return delim.toString() to j + 1
        }
        if (cmd == "begin") {
            val env = readGroup(src, at)
            val body = readUntilEnd(src, env.second, env.first)
            return environment(env.first, body.first, unknown) to body.second
        }
        if (cmd == "end") {
            val grp = readGroup(src, at)
            return "" to grp.second
        }
        if (cmd in functions) return cmd to at
        if (cmd in symbols) return symbols.getValue(cmd) to at
        if (unknown == "keep") return "\\" + cmd to at
        val j = skipSpace(src, at)
        if (j < src.length && src[j] == '{') {
            val grp = readGroup(src, at)
            return convert(grp.first, unknown) to grp.second
        }
        return "" to at
    }

    private fun environment(env: String, body: String, unknown: String): String {
        val name = env.trim().trimEnd('*')
        val rows = envSplit.split(body).filter { it.isNotBlank() }.map { row ->
            row.split('&').map { convert(it.trim(), unknown) }
        }
        if (rows.isEmpty()) return convert(body, unknown)
        if (name == "cases") {
            val bits = rows.map { row ->
                if (row.size >= 2) "${row[0]} (${row[1]})" else row[0]
            }
            return "{ " + bits.joinToString("; ") + " }"
        }
        val joined = rows.joinToString("; ") { row ->
            row.filter { it.isNotEmpty() }.joinToString("  ")
        }
        return when (name) {
            "bmatrix", "Bmatrix" -> "[$joined]"
            "pmatrix" -> "($joined)"
            "vmatrix" -> "|$joined|"
            else -> joined
        }
    }

    private fun script(body: String, table: Map<String, String>, mark: String): String {
        val text = body.trim()
        if (text.isEmpty()) return ""
        if (mark == "^" && text in setOf("∘", "circ", "o")) return "°"
        if (text.all { it.isWhitespace() || it.toString() in table }) {
            return text.map { ch -> if (ch.isWhitespace()) ch.toString() else table.getValue(ch.toString()) }.joinToString("")
        }
        return if (text.length > 1) "$mark($text)" else "$mark$text"
    }

    private fun paren(body: String): String {
        val text = body.trim()
        if (text.isEmpty()) return text
        if (simple.matchEntire(text) != null) return text
        if (text.first() == '(' && text.last() == ')' && balanced(text.substring(1, text.length - 1))) return text
        return "($text)"
    }

    private fun balanced(src: String): Boolean {
        var depth = 0
        for (ch in src) {
            if (ch == '(') depth += 1
            else if (ch == ')') {
                depth -= 1
                if (depth < 0) return false
            }
        }
        return depth == 0
    }

    private fun readCmd(src: String, i: Int): Pair<String, Int> {
        var at = i + 1
        if (at >= src.length) return "\\" to at
        val ch = src[at]
        if (ch.isLetter()) {
            var j = at + 1
            while (j < src.length && src[j].isLetter()) j += 1
            return src.substring(at, j) to j
        }
        return ch.toString() to at + 1
    }

    private fun skipSpace(src: String, i: Int): Int {
        var at = i
        while (at < src.length && src[at].isWhitespace()) at += 1
        return at
    }

    private fun readGroup(src: String, i: Int): Pair<String, Int> {
        var at = skipSpace(src, i)
        if (at >= src.length) return "" to at
        if (src[at] == '{') {
            var depth = 1
            at += 1
            val start = at
            while (at < src.length && depth != 0) {
                if (src[at] == '\\') {
                    at += 2
                    continue
                }
                if (src[at] == '{') depth += 1
                else if (src[at] == '}') depth -= 1
                at += 1
            }
            val body = if (depth == 0) src.substring(start, at - 1) else src.substring(start)
            return body to at
        }
        if (src[at] == '\\') {
            val cmd = readCmd(src, at)
            return "\\" + cmd.first to cmd.second
        }
        return src[at].toString() to at + 1
    }

    private fun readBracket(src: String, i: Int): Pair<String, Int> {
        var at = i + 1
        val start = at
        var depth = 1
        while (at < src.length && depth != 0) {
            if (src[at] == '[') depth += 1
            else if (src[at] == ']') depth -= 1
            at += 1
        }
        val body = if (depth == 0) src.substring(start, at - 1) else src.substring(start)
        return body to at
    }

    private fun readUntilEnd(src: String, i: Int, env: String): Pair<String, Int> {
        val needle = "\\end{$env}"
        val at = src.indexOf(needle, i)
        if (at < 0) return src.substring(i) to src.length
        return src.substring(i, at) to at + needle.length
    }
}
