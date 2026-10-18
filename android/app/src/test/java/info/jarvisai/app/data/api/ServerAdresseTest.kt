package info.jarvisai.app.data.api

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.URI

/**
 * Code-Review 2026-10-18: ServerAdresse ersetzt sechs Kopien der ws->http-Umrechnung.
 * Die alten Fassungen stehen hier woertlich als Referenz; fuer alle Adressen, die
 * SettingsDataStore.save() speichern kann, muss der Helfer dasselbe liefern.
 */
class ServerAdresseTest {

    // --- Alte Fassungen (Stand vor dem Review), nur als Vergleich ---------------

    /** ServerTtsPlayer.toHttps */
    private fun altToHttps(wsUrl: String): String {
        var u = wsUrl.trimEnd('/').removeSuffix("/ws")
        u = u.replace("wss://", "https://").replace("ws://", "http://")
        return u
    }

    /** ChatViewModel.sendFeedback / ChatRepository.fetchMyBlock */
    private fun altFeedback(url: String): String =
        url.replace("wss://", "https://").replace("ws://", "http://")
            .removeSuffix("/ws").removeSuffix("/ws/")

    /** SettingsViewModel.basisUrl / loginWithCredentials / IssuesRepository.baseUrl */
    private fun altBasis(serverUrl: String): String {
        val httpUrl = serverUrl.trimEnd('/').let {
            when {
                it.startsWith("wss://") -> "https://" + it.removePrefix("wss://")
                it.startsWith("ws://")  -> "http://" + it.removePrefix("ws://")
                it.isBlank()            -> ""
                !it.startsWith("http")  -> "https://$it"
                else                    -> it
            }
        }
        return try {
            val parsed = URI(httpUrl)
            val port = if (parsed.port > 0) ":${parsed.port}" else ""
            "${parsed.scheme}://${parsed.host}$port"
        } catch (_: Exception) { httpUrl }
    }

    /** JarvisWebSocket.buildWsUrl */
    private fun altWs(url: String): String {
        val base = when {
            url.startsWith("wss://") || url.startsWith("ws://") -> url
            url.startsWith("https://") -> "wss://${url.removePrefix("https://")}"
            url.startsWith("http://")  -> "ws://${url.removePrefix("http://")}"
            else -> "wss://$url"
        }
        return if (base.endsWith("/ws")) base else "${base.trimEnd('/')}/ws"
    }

    // Adressen, wie SettingsDataStore.save() sie ablegt (Schema da, ohne "/" am Ende)
    private val gespeichert = listOf(
        "https://beispiel.de",
        "https://beispiel.de:8443",
        "https://beispiel.de/ws",
        "https://beispiel.de:8443/ws",
        "http://192.0.2.10",
        "http://192.0.2.10:8080/ws",
        "wss://beispiel.de/ws",
        "ws://192.0.2.10:8080/ws",
        "wss://beispiel.de:8443",
    )

    @Test
    fun positivkontrolle_liste_nicht_leer() {
        // Ohne Eingaben waeren die Vergleichstests trivial gruen
        assertTrue(gespeichert.size >= 5)
    }

    @Test
    fun httpBasis_wie_alte_tts_und_feedback_umrechnung() {
        for (a in gespeichert) {
            assertEquals("toHttps fuer $a", altToHttps(a), ServerAdresse.httpBasis(a))
            assertEquals("Feedback fuer $a", altFeedback(a), ServerAdresse.httpBasis(a))
        }
    }

    @Test
    fun ursprung_wie_alte_basisUrl() {
        for (a in gespeichert + listOf("beispiel.de", "beispiel.de:8443/ws", "https://beispiel.de/")) {
            assertEquals("basisUrl fuer $a", altBasis(a), ServerAdresse.ursprung(a))
        }
    }

    @Test
    fun wsAdresse_wie_alte_buildWsUrl() {
        for (a in gespeichert + listOf("beispiel.de", "https://beispiel.de/")) {
            assertEquals("buildWsUrl fuer $a", altWs(a), ServerAdresse.wsAdresse(a))
        }
    }

    @Test
    fun konkrete_werte() {
        assertEquals("https://beispiel.de:8443", ServerAdresse.httpBasis("wss://beispiel.de:8443/ws"))
        assertEquals("http://192.0.2.10:8080", ServerAdresse.ursprung("ws://192.0.2.10:8080/ws"))
        assertEquals("https://beispiel.de", ServerAdresse.ursprung("beispiel.de/ws"))
        assertEquals("wss://beispiel.de/ws", ServerAdresse.wsAdresse("https://beispiel.de"))
        assertEquals("", ServerAdresse.ursprung(""))
        assertEquals("", ServerAdresse.httpBasis("  "))
        // Abweichung zur alten Feedback-Fassung: Schraegstrich nach /ws wird mit entfernt
        assertEquals("https://beispiel.de", ServerAdresse.httpBasis("https://beispiel.de/ws/"))
    }
}
