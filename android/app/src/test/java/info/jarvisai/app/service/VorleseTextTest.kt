package info.jarvisai.app.service

import org.junit.Assert.assertEquals
import org.junit.Test

/** Gleiche Faelle wie tests/test_meta_marke.py – beide Seiten muessen dasselbe tun. */
class VorleseTextTest {
    private val m = "⁣"

    @Test fun ohneMarkeUnveraendert() =
        assertEquals("Hallo Welt", VorleseText.ohneMeta("Hallo Welt"))

    @Test fun blockWirdEntfernt() =
        assertEquals("Antwort   Rest", VorleseText.ohneMeta("Antwort $m[Prompt optimiert] xyz$m Rest"))

    @Test fun zweiBloecke() =
        assertEquals("  A   B  ", VorleseText.ohneMeta("${m}x$m A ${m}y$m B ${m}z$m"))

    @Test fun loseMarkeEntferntNurSich() =
        assertEquals("Antwort Rest", VorleseText.ohneMeta("Antwort ${m}Rest"))

    @Test fun nurMetaErgibtLeer() =
        assertEquals("", VorleseText.ohneMeta("$m[Quellen] a.pdf$m").trim())
}
