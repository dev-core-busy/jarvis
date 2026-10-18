package info.jarvisai.app.data.api

import java.net.URI

/**
 * Umrechnung der gespeicherten Server-Adresse in die Formen, die die App braucht.
 *
 * Code-Review 2026-10-18: dieselbe ws->http-Umrechnung stand an sechs Stellen
 * (ServerTtsPlayer.toHttps, SettingsViewModel.basisUrl + inline im Login,
 * ChatViewModel.sendFeedback, ChatRepository.fetchMyBlock, IssuesRepository.baseUrl)
 * und war leicht unterschiedlich. Die Stellen behalten ihr bisheriges Verhalten,
 * es gibt deshalb zwei Formen:
 *  - [httpBasis]: Schema auf http(s) umgestellt, abschliessendes "/ws" entfernt,
 *    ein evtl. weiterer Pfad bleibt (TTS, Feedback, Sperr-Info).
 *  - [ursprung]: nur Schema + Host + Port (Login, Zertifikatspruefung, Issues).
 * Rein funktional (nur java.net.URI), damit als JVM-Unit-Test pruefbar.
 */
object ServerAdresse {

    /** Stellt das Schema auf http/https um; ohne Schema gilt https. Leer bleibt leer. */
    fun mitHttpSchema(adresse: String): String {
        val a = adresse.trim().trimEnd('/')
        return when {
            a.isBlank()              -> ""
            a.startsWith("wss://")   -> "https://" + a.removePrefix("wss://")
            a.startsWith("ws://")    -> "http://" + a.removePrefix("ws://")
            a.startsWith("https://") || a.startsWith("http://") -> a
            else                     -> "https://$a"
        }
    }

    /** http(s)-Basis ohne abschliessendes "/ws" und ohne Schraegstrich am Ende. */
    fun httpBasis(adresse: String): String =
        mitHttpSchema(adresse).removeSuffix("/ws").trimEnd('/')

    /** Nur Schema + Host + Port; bei nicht zerlegbarer Adresse die http(s)-Form. */
    fun ursprung(adresse: String): String {
        val http = mitHttpSchema(adresse)
        if (http.isBlank()) return ""
        return try {
            val u = URI(http)
            val host = u.host ?: return http
            val port = if (u.port > 0) ":${u.port}" else ""
            "${u.scheme}://$host$port"
        } catch (_: Exception) {
            http
        }
    }

    /** WebSocket-Adresse: ws(s)-Schema und Pfad "/ws" am Ende. */
    fun wsAdresse(adresse: String): String {
        val a = adresse.trim()
        val basis = when {
            a.startsWith("wss://") || a.startsWith("ws://") -> a
            a.startsWith("https://") -> "wss://" + a.removePrefix("https://")
            a.startsWith("http://")  -> "ws://" + a.removePrefix("http://")
            else                     -> "wss://$a"
        }
        return if (basis.endsWith("/ws")) basis else "${basis.trimEnd('/')}/ws"
    }
}
