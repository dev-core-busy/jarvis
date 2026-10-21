package info.jarvisai.app.data.prefs

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/**
 * 2026-10-21: der API-Schluessel stand im Klartext im DataStore. Geprueft wird die
 * Logik des Tresors mit einem Software-Schluessel – der Android-Keystore selbst
 * ist im JVM-Test nicht vorhanden, die Verschluesselung ist dieselbe.
 */
class SchluesselTresorTest {

    private fun neuerSchluessel(): SecretKey =
        KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()

    private val schluessel = neuerSchluessel()
    private val tresor = SchluesselTresor { schluessel }
    private val geheim = "jv-api-Beispiel-0123456789abcdef"

    @Test
    fun hinUndZurueck() {
        assertEquals(geheim, tresor.entpacken(tresor.verpacken(geheim)))
        assertEquals("", tresor.entpacken(tresor.verpacken("")))
        assertEquals("äöü€", tresor.entpacken(tresor.verpacken("äöü€")))
    }

    @Test
    fun gespeicherteFormVerraetDenKlartextNicht() {
        val v = tresor.verpacken(geheim)
        assertTrue(v.startsWith(SchluesselTresor.PRAEFIX))
        assertFalse(v.contains(geheim))
        val roh = String(Base64.getDecoder().decode(v.removePrefix(SchluesselTresor.PRAEFIX)), Charsets.ISO_8859_1)
        assertFalse(roh.contains(geheim))
    }

    @Test
    fun jederAufrufMitNeuemIv() {
        assertNotEquals(tresor.verpacken(geheim), tresor.verpacken(geheim))
    }

    @Test
    fun manipulationWirdErkannt() {
        val v = tresor.verpacken(geheim)
        val roh = Base64.getDecoder().decode(v.removePrefix(SchluesselTresor.PRAEFIX))
        roh[roh.size - 1] = (roh[roh.size - 1].toInt() xor 1).toByte()
        assertNull(tresor.entpacken(SchluesselTresor.PRAEFIX + Base64.getEncoder().encodeToString(roh)))
    }

    @Test
    fun fremderSchluesselLiefertNichts() {
        val v = tresor.verpacken(geheim)
        assertNull(SchluesselTresor { neuerSchluessel() }.entpacken(v))
    }

    @Test
    fun klartextUndKaputteFormLiefernNichts() {
        assertNull(tresor.entpacken(geheim))            // Altform (Klartext) ist keine v1-Form
        assertNull(tresor.entpacken("v1:"))
        assertNull(tresor.entpacken("v1:kein-base64!"))
        assertNull(tresor.entpacken("v1:" + Base64.getEncoder().encodeToString(ByteArray(12))))
    }
}
