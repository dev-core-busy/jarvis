package info.jarvisai.app.desktop

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pentest C1 / BSI H9 (2026-11-08): Logik des Bestaetigungsdialogs. Gleiche
 * Zusagen wie der Go-Test der Windows-App (tests/test_windows_app_bestaetigung.py).
 * Sonderzeichen werden ueber Codepunkte gebaut, nicht als Escape geschrieben –
 * ein Werkzeug, das Escapes beim Schreiben aufloest, machte sonst aus der Probe
 * still etwas anderes.
 */
class BestaetigungTest {

    private fun zeichen(cp: Int) = String(Character.toChars(cp))

    @Test
    fun positivkontrolle_gueltigeAnfrage() {
        val a = Bestaetigung.parse(
            """{"type":"bestaetigung_anfrage","id":"k1","werkzeug":"android_desktop","klasse":"shell",""" +
                """"argumente":[["action","shell_exec"],["cmd","ls /sdcard"]],"frist_s":120}"""
        )
        assertNotNull(a)
        assertEquals("k1", a!!.id)
        assertEquals("ls /sdcard", a.argument("cmd"))
        assertEquals(120, a.fristS)
    }

    @Test
    fun ohneKennung_keineAnfrage() {
        assertNull(Bestaetigung.parse("""{"type":"bestaetigung_anfrage","id":"  "}"""))
        assertNull(Bestaetigung.parse("""{"type":"bestaetigung_anfrage"}"""))
    }

    @Test
    fun fremderTyp_keineAnfrage() {
        assertNull(Bestaetigung.parse("""{"type":"status","id":"k1"}"""))
        assertNull(Bestaetigung.parse("kein json"))
    }

    @Test
    fun kaputteArgumente_einzelnUebersprungen() {
        val a = Bestaetigung.parse(
            """{"type":"bestaetigung_anfrage","id":"k2","argumente":[["action","shell_exec"],42,["nur"],["cmd","id"]]}"""
        )
        assertNotNull(a)
        assertEquals(2, a!!.argumente.size)
        assertEquals("id", a.argument("cmd"))
    }

    @Test
    fun textNenntJedesArgument() {
        val a = BestaetigungsAnfrage("k", "android_desktop", "shell",
            listOf("action" to "shell_exec", "cmd" to "rm -r /sdcard/x", "cwd" to "/sdcard"), 120)
        val t = Bestaetigung.text(a, "de")
        for (muss in listOf("rm -r /sdcard/x", "/sdcard", "cwd", "Befehl")) {
            assertTrue("Dialogtext nennt '$muss' nicht: $t", t.contains(muss))
        }
    }

    @Test
    fun steuerUndRichtungszeichenSichtbar() {
        val rlo = zeichen(0x202e)
        val esc = zeichen(0x1b)
        val a = BestaetigungsAnfrage("k", "android_desktop", "shell",
            listOf("action" to "shell_exec", "cmd" to "echo a${rlo}gnp.sh$esc[2J"), 120)
        val t = Bestaetigung.text(a, "de")
        assertFalse("Richtungszeichen unsichtbar im Dialog", t.contains(rlo))
        assertFalse("Steuerzeichen unsichtbar im Dialog", t.contains(esc))
        assertTrue("Ersatzzeichen fehlt", t.contains(zeichen(0xFFFD)))
    }

    @Test
    fun laengeGedeckelt() {
        val a = BestaetigungsAnfrage("k", "android_desktop", "shell",
            listOf("action" to "shell_exec", "cmd" to "x".repeat(50000)), 120)
        val t = Bestaetigung.text(a, "de")
        assertTrue("zu lang: ${t.length}", t.codePointCount(0, t.length) <= Bestaetigung.TEXT_MAX + 1)
        assertTrue("Kuerzung nicht benannt", t.contains("gekürzt"))
    }

    @Test
    fun fristVorDerServerfrist() {
        val f = Bestaetigung.fristMs(120)
        assertTrue("Frist $f nicht knapp vor 120 s", f in 100_000L until 120_000L)
        assertTrue(Bestaetigung.fristMs(0) > 0)
        assertTrue(Bestaetigung.fristMs(3) >= 10_000L)
    }
}
