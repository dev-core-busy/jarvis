package info.jarvisai.app.desktop

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull

/**
 * Bestaetigung wirksamer Aktionen in der Android-App (BSI H9, Pentest C1).
 *
 * WARUM: seit C1 brauchen Shell-Befehl und App-Start auf dem eigenen Geraet
 * eine Freigabe durch den Menschen. Der Server schickt dafuer
 * `bestaetigung_anfrage` an den Client, von dem der Auftrag kam, und wartet auf
 * `bestaetigung_antwort` mit derselben `id`. Ein Client meldet mit
 * `"bestaetigung": true` im Auftrag, dass er den Dialog zeigen kann – ohne das
 * Feld weist der Server die Aktion ab ("Client ohne Dialog").
 *
 * Diese Datei ist bewusst frei von Android-Klassen: Dekodieren, Dialogtext und
 * Frist lassen sich so ohne Geraet pruefen (JVM-Test
 * `BestaetigungTest`, Waechter `tests/test_android_app_bestaetigung.py`).
 * Gleiche Regeln wie `windows-app-go/bestaetigung.go`.
 */
data class BestaetigungsAnfrage(
    val id: String,
    val werkzeug: String,
    val klasse: String,
    val argumente: List<Pair<String, String>>,
    val fristS: Int,
) {
    fun argument(name: String): String = argumente.firstOrNull { it.first == name }?.second ?: ""
}

object Bestaetigung {
    /** Obergrenzen, damit der Dialog nicht ueber den Bildschirm waechst. */
    const val WERT_MAX = 400
    const val TEXT_MAX = 1800

    /**
     * Liest eine Server-Nachricht; `null`, wenn es keine Bestaetigungsanfrage
     * MIT Kennung ist (ohne Kennung koennte keine Antwort zugeordnet werden).
     * Argumente in falscher Form werden einzeln uebersprungen – eine verworfene
     * Anfrage liefe beim Server in die Frist, der Benutzer saehe nichts.
     */
    fun parse(text: String): BestaetigungsAnfrage? {
        val o = try {
            Json.parseToJsonElement(text) as? JsonObject
        } catch (e: Exception) {
            null
        } ?: return null
        if ((o["type"] as? JsonPrimitive)?.contentOrNull != "bestaetigung_anfrage") return null
        val id = (o["id"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        if (id.isBlank()) return null
        val args = (o["argumente"] as? JsonArray)?.mapNotNull { e ->
            val paar = e as? JsonArray ?: return@mapNotNull null
            if (paar.size != 2) return@mapNotNull null
            val k = (paar[0] as? JsonPrimitive)?.takeIf { it.isString }?.content
            val v = (paar[1] as? JsonPrimitive)?.takeIf { it.isString }?.content
            if (k == null || v == null) null else k to v
        } ?: emptyList()
        return BestaetigungsAnfrage(
            id = id,
            werkzeug = (o["werkzeug"] as? JsonPrimitive)?.contentOrNull ?: "",
            klasse = (o["klasse"] as? JsonPrimitive)?.contentOrNull ?: "",
            argumente = args,
            fristS = (o["frist_s"] as? JsonPrimitive)?.intOrNull ?: 0,
        )
    }

    private fun sichtbar(cp: Int): Boolean =
        cp == '\n'.code || cp == '\t'.code ||
            (cp >= 0x20 && cp != 0x7f && !(cp in 0x80..0x9f) &&
                cp != 0x200b && cp != 0x202e && cp !in 0x2066..0x2069)

    /**
     * Steuer- und Richtungszeichen sichtbar ersetzen und kuerzen – ein
     * unsichtbares Zeichen im Befehl hiesse, der Mensch gibt etwas frei, das er
     * nicht gesehen hat. Der Kuerzungshinweis steht VORN.
     */
    fun lesbar(s: String, max: Int, lang: String): String {
        val b = StringBuilder()
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            if (sichtbar(cp)) b.appendCodePoint(cp) else b.append('\uFFFD')
            i += Character.charCount(cp)
        }
        val out = b.toString()
        if (out.codePointCount(0, out.length) <= max) return out
        val ende = out.offsetByCodePoints(0, max)
        return (if (lang == "en") "[truncated] " else "[gekürzt] ") + out.substring(0, ende) + "…"
    }

    fun titel(lang: String): String =
        if (lang == "en") "Jarvis asks for confirmation" else "Jarvis bittet um Bestätigung"

    fun kopf(a: BestaetigungsAnfrage, lang: String): String {
        val en = lang == "en"
        val aktion = a.argument("action")
        return when {
            a.werkzeug == "android_desktop" && aktion == "shell_exec" ->
                if (en) "Jarvis wants to run a command on this device:"
                else "Jarvis möchte auf diesem Gerät einen Befehl ausführen:"
            a.werkzeug == "android_desktop" && aktion == "launch_app" ->
                if (en) "Jarvis wants to start an app on this device:"
                else "Jarvis möchte auf diesem Gerät eine App starten:"
            else ->
                (if (en) "Jarvis wants to perform the following action: "
                else "Jarvis möchte folgende Aktion ausführen: ") + lesbar(a.werkzeug, 80, lang)
        }
    }

    /** Vollstaendiger Dialogtext: Kopf, JEDES Argument, Hinweis. */
    fun text(a: BestaetigungsAnfrage, lang: String): String {
        val en = lang == "en"
        val b = StringBuilder(kopf(a, lang)).append("\n\n")
        if (a.argumente.isEmpty()) b.append(if (en) "(no details)" else "(keine Angaben)").append('\n')
        for ((k, v) in a.argumente) {
            b.append(lesbar(k, 60, lang)).append(": ").append(lesbar(v, WERT_MAX, lang)).append('\n')
        }
        b.append('\n').append(
            if (en) "Only allow if you gave this instruction yourself."
            else "Nur zulassen, wenn Sie diesen Auftrag selbst gegeben haben."
        )
        val s = b.toString()
        if (s.codePointCount(0, s.length) <= TEXT_MAX) return s
        return s.substring(0, s.offsetByCodePoints(0, TEXT_MAX)) + "…"
    }

    /** Der Dialog schliesst kurz VOR der Serverfrist (gilt dann als abgelehnt). */
    fun fristMs(fristS: Int): Long {
        val f = if (fristS <= 0) 120 else fristS
        return maxOf(10_000L, (f - 5) * 1000L)
    }
}
