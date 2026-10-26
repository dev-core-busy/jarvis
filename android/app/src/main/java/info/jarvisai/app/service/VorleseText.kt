package info.jarvisai.app.service

/**
 * Meta-Angaben zwischen zwei U+2063 (INVISIBLE SEPARATOR) werden nicht vorgelesen.
 *
 * Gemeldet 2026-10-26: ein vorgeschalteter Proxy klammert Meta-Angaben einer
 * Antwort (verbesserter Prompt, Eskalation, Quellenliste) in U+2063; die App las
 * "[Prompt optimiert] ..." vor. Dieselbe Regel wie backend/meta_marke.py – der
 * Server filtert /api/tts selbst, hier geht es um den lokalen Rueckfall
 * (Android-TTS), der den Server nicht beruehrt.
 *
 * Eine einzelne Marke ohne Gegenstueck entfernt nur sich selbst: den Rest der
 * Antwort zu verschlucken waere bei einem abgeschnittenen Block schlimmer.
 */
object VorleseText {
    const val MARKE = '⁣'
    private val BLOCK = Regex("⁣[^⁣]*⁣")

    fun ohneMeta(text: String): String {
        if (text.indexOf(MARKE) < 0) return text
        return BLOCK.replace(text, " ").replace(MARKE.toString(), "")
    }
}
