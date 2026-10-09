package app.arelis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Same cases as the desktop mathtext tests. Output is the unicode line. */
class MathTextTest {
    @Test
    fun boxedDoesNotPrintTheCommandName() {
        val out = MathText.flatten("$$\\boxed{\\theta_{opt} \\approx 35.3^\\circ}$$")
        assertFalse(out.contains("boxed"))
        assertTrue(out.contains("θ"))
        assertTrue(out.contains("≈"))
        assertTrue(out.contains("35.3"))
        assertTrue(out.contains("°"))
        assertFalse(out.contains("\\boxed"))
        assertEquals("\nθₒₚₜ ≈ 35.3°\n", out)
    }

    @Test
    fun casClosedFormKeepsLogAndFrac() {
        val out = MathText.flatten("$$\\frac{x^{3}}{6} + 25x\\log(x-3) - 75\\log(x-3)$$")
        assertTrue(out.contains("log"))
        assertFalse(out.contains("\\log"))
        assertFalse(out.contains("\\frac"))
        assertTrue(out.contains("x³"))
        assertFalse(out.contains("$$"))
        assertEquals("\nx³/6 + 25xlog(x-3) - 75log(x-3)\n", out)
    }

    @Test
    fun priceStaysADollarAndInlineMathFlattens() {
        val out = MathText.flatten("cost is \$5 and \$\\log x\$ stays math")
        assertTrue(out.contains("\$5"))
        assertTrue(out.contains("log x"))
        assertFalse(out.contains("\\log"))
        assertEquals("cost is \$5 and log x stays math", out)
    }

    @Test
    fun integralDelimitersLeave() {
        val out = MathText.flatten(
            "The integral of \\( x^2 \\) is \\[\\int x^2 \\, dx = \\frac{x^3}{3} + C\\]",
        )
        assertFalse(out.contains("\\("))
        assertFalse(out.contains("\\["))
        assertTrue(out.contains("x²"))
        assertTrue(out.contains("∫"))
        assertTrue(out.contains("x³"))
        assertTrue(out.contains("/3"))
        assertEquals("The integral of x² is \n∫ x²   dx = x³/3 + C\n", out)
    }

    @Test
    fun sqrtKeepsACompoundRadicandGrouped() {
        assertEquals("√(x+1)", MathText.texToPlain("\\sqrt{x+1}"))
        assertEquals("√x", MathText.texToPlain("\\sqrt{x}"))
        assertEquals("³√x", MathText.texToPlain("\\sqrt[3]{x}"))
    }

    @Test
    fun nestedFracAndGreek() {
        assertEquals("1/(1+1/x)", MathText.texToPlain("\\frac{1}{1+\\frac{1}{x}}"))
        val greek = MathText.texToPlain("\\alpha + \\beta")
        assertTrue(greek.contains("α"))
        assertTrue(greek.contains("β"))
        assertEquals("α + β", greek)
    }

    @Test
    fun subscriptsAndLimits() {
        val out = MathText.texToPlain("\\sum_{n=1}^{N} x_n")
        assertTrue(out.contains("Σ"))
        assertTrue(out.contains("xₙ"))
        assertEquals("Σₙ₌₁^N xₙ", out)
    }

    @Test
    fun codeFenceKeepsTexSource() {
        val out = MathText.flatten("see\n```\n\$\\frac{1}{2}\$\n```\ndone")
        assertTrue(out.contains("\\frac"))
        assertTrue(out.contains("```"))
        assertFalse(out.split("```")[0].contains("1/2"))
    }

    @Test
    fun windowsPathIsNotEaten() {
        val out = MathText.flatten("read C:\\Users\\you\\notes.md then \\frac{1}{2}")
        assertTrue(out.contains("\\Users"))
        assertTrue(out.contains("1/2"))
        assertFalse(out.contains("\\frac"))
        assertTrue(MathText.flatten("open C:\\input next").contains("C:\\input"))
        assertFalse(MathText.flatten("open C:\\input next").contains("∈"))
        assertTrue(MathText.flatten("see folder\\log then done").contains("folder\\log"))
    }

    @Test
    fun bareIntegralScriptsAndThinSpace() {
        val out = MathText.flatten("\\int_0^\\infty e^{-x}\\,dx")
        assertTrue(out.contains("∫"))
        assertFalse(out.contains("\\int"))
        assertFalse(out.contains("\\,"))
        assertTrue(out.contains("e⁻ˣ"))
        assertEquals("∫₀^∞ e⁻ˣ dx", out)
    }

    @Test
    fun rightAfterADigitIsTexNotAPath() {
        val out = MathText.flatten("latex: \\left[ -5,  2\\right]")
        assertFalse(out.contains("\\right"))
        assertFalse(out.contains("\\left"))
        assertTrue(out.contains("[ -5,  2]"))
        assertEquals("latex: [ -5,  2]", out)
    }

    @Test
    fun casSympyLatexFlattens() {
        val latex = "\\frac{x^{3}}{6} + 25 x \\log{\\left(x - 3 \\right)} - 75 \\log{\\left(x - 3 \\right)}"
        val out = MathText.flatten("$$" + latex + "$$")
        assertTrue(out.contains("log"))
        assertFalse(out.contains("\\log"))
        assertFalse(out.contains("\\left"))
        assertTrue(out.contains("x³"))
        assertTrue(out.contains("6"))
        assertEquals("\nx³/6 + 25 x log(x - 3 ) - 75 log(x - 3 )\n", out)
    }

    @Test
    fun displayMathAndInlineSentence() {
        val energy = MathText.flatten("The energy is \$\$\\frac{1}{2}mv^2\$\$ as usual.")
        assertTrue(energy.contains("1/2mv²"))
        assertFalse(energy.contains("\\frac"))
        assertFalse(energy.contains("$$"))
        assertEquals("The energy is \n1/2mv²\n as usual.", energy)
        val force = MathText.flatten("Force is \$F = ma\$ on the nose.")
        assertEquals("Force is F = ma on the nose.", force)
    }

    @Test
    fun rootAndBubbleMatchTheDesktop() {
        assertEquals(
            "The root is \n√(x+1)\n.",
            MathText.flatten("The root is \$\$\\sqrt{x+1}\$\$.")
        )
        assertEquals(
            "The integral is \n∫ x²   dx = x³/3 + C\n",
            MathText.flatten("The integral is \$\$\\int x^2 \\, dx = \\frac{x^3}{3} + C\$\$"),
        )
    }

    @Test
    fun symbolsTheDesktopMaps() {
        assertEquals("a · b × c ≤ d ∞", MathText.texToPlain("a \\cdot b \\times c \\leq d \\infty"))
        assertEquals("a ≤ b ≥ c ≠ d", MathText.texToPlain("a \\le b \\ge c \\neq d"))
    }

    @Test
    fun replyHidesMathMarkers() {
        val doc = formatReply("Force is \$x^2\$ today.", ReplyInk(1, 2, 3, 4))
        assertEquals("Force is x² today.", doc.visible)
        assertFalse(doc.visible.contains("\$"))
    }
}
