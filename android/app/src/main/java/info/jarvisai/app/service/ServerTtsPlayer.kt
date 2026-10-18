package info.jarvisai.app.service

import info.jarvisai.app.data.api.ServerAdresse
import info.jarvisai.app.data.tls.ServerVertrauen
import android.content.Context
import android.media.MediaPlayer
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "ServerTtsPlayer"

data class TtsVoice(
    val id: String,
    val display: String,
    val gender: String,
    val locale: String,
)

@Singleton
class ServerTtsPlayer @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    // Zertifikat: System/Firmen-CA oder bestaetigt (BSI M11, ServerVertrauen)
    private val httpClient: OkHttpClient by lazy {
        ServerVertrauen.anwenden(OkHttpClient.Builder()).build()
    }

    // Code-Review 2026-10-18: eigene Umrechnung toHttps() durch ServerAdresse ersetzt
    private fun toHttps(wsUrl: String): String = ServerAdresse.httpBasis(wsUrl)

    // Code-Review 2026-10-18: die laufende Wiedergabe wird gemerkt, damit eine neue
    // sie beendet (frueher liefen Antworten uebereinander) und stop() sie abbrechen kann.
    private val sperre = Any()
    private var player: MediaPlayer? = null
    private var playerDatei: File? = null

    /** Spricht Text via Server edge-tts. Gibt true zurück wenn erfolgreich. */
    suspend fun speak(serverUrl: String, apiKey: String, text: String, voice: String): Boolean =
        withContext(Dispatchers.IO) {
            try {
                val url = toHttps(serverUrl) + "/api/tts"
                val body = JSONObject().apply {
                    put("text", text)
                    put("voice", voice)
                }.toString().toRequestBody("application/json".toMediaType())
                val req = Request.Builder()
                    .url(url)
                    .addHeader("X-API-Key", apiKey)
                    .post(body)
                    .build()
                // Code-Review 2026-10-18: Response per use{} schliessen (vorher offen gelassen)
                val bytes = httpClient.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) {
                        Log.w(TAG, "Server TTS HTTP ${resp.code}")
                        return@withContext false
                    }
                    resp.body?.bytes() ?: return@withContext false
                }
                playMp3Bytes(bytes)
            } catch (e: Exception) {
                Log.e(TAG, "Server TTS error: ${e.message}")
                false
            }
        }

    /** Vorschau einer Stimme mit kurzem Test-Text. */
    suspend fun preview(serverUrl: String, apiKey: String, voice: String): Boolean =
        speak(serverUrl, apiKey, "Hallo, ich bin Jarvis.", voice)

    /** Alle verfügbaren Stimmen vom Server laden. */
    suspend fun fetchVoices(serverUrl: String, apiKey: String): List<TtsVoice> =
        withContext(Dispatchers.IO) {
            try {
                val url = toHttps(serverUrl) + "/api/tts/voices"
                val req = Request.Builder()
                    .url(url)
                    .addHeader("X-API-Key", apiKey)
                    .get()
                    .build()
                val body = httpClient.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) return@withContext emptyList()
                    resp.body?.string() ?: return@withContext emptyList()
                }
                val arr = org.json.JSONArray(body)
                (0 until arr.length()).map { i ->
                    val o = arr.getJSONObject(i)
                    TtsVoice(
                        id      = o.getString("name"),
                        display = o.optString("display", o.getString("name")),
                        gender  = o.optString("gender", ""),
                        locale  = o.optString("locale", ""),
                    )
                }
            } catch (e: Exception) {
                Log.e(TAG, "fetchVoices error: ${e.message}")
                emptyList()
            }
        }

    /** Beendet eine laufende Server-Wiedergabe und raeumt Player + Temp-Datei weg. */
    fun stop() {
        synchronized(sperre) { freigebenGesperrt(player) }
    }

    /** Gibt [mp] frei, falls er noch der aktuelle Player ist. Nur unter [sperre]. */
    private fun freigebenGesperrt(mp: MediaPlayer?) {
        if (mp == null || mp !== player) return
        runCatching { mp.stop() }
        runCatching { mp.release() }
        playerDatei?.delete()
        player = null
        playerDatei = null
    }

    /**
     * Code-Review 2026-10-18: frueher ohne setOnErrorListener - bei einem
     * Wiedergabefehler blieben Player und Temp-Datei liegen, ebenso bei einer
     * Ausnahme in prepare(). Jetzt werden beide in jedem Ausgang freigegeben.
     * Rueckgabe: true, wenn die Wiedergabe gestartet wurde.
     */
    private fun playMp3Bytes(data: ByteArray): Boolean {
        var tmp: File? = null
        val mp = MediaPlayer()
        return try {
            tmp = File.createTempFile("jarvis_tts_", ".mp3", context.cacheDir)
            tmp.writeBytes(data)
            synchronized(sperre) {
                // Vorherige Wiedergabe beenden statt ueberlappen zu lassen
                freigebenGesperrt(player)
                player = mp
                playerDatei = tmp
            }
            mp.setOnCompletionListener { synchronized(sperre) { freigebenGesperrt(it) } }
            mp.setOnErrorListener { p, what, extra ->
                Log.e(TAG, "MP3-Wiedergabefehler what=$what extra=$extra")
                synchronized(sperre) { freigebenGesperrt(p) }
                true
            }
            mp.setDataSource(tmp.absolutePath)
            mp.prepare()
            mp.start()
            true
        } catch (e: Exception) {
            Log.e(TAG, "MP3 playback error: ${e.message}")
            synchronized(sperre) {
                if (player === mp) {
                    freigebenGesperrt(mp)  // loescht auch die Temp-Datei
                } else {
                    runCatching { mp.release() }
                    tmp?.delete()
                }
            }
            false
        }
    }
}
