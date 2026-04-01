package info.jarvisai.app.service

import android.content.Context
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "ServerTtsPlayer"

/**
 * Spielt TTS-Audio vom Jarvis-Server ab (edge-tts, Microsoft Neural Voices).
 * POST /api/tts  → MP3-Audio
 * GET  /api/tts/voices → Stimmen-Liste
 */
@Singleton
class ServerTtsPlayer @Inject constructor(
    @ApplicationContext private val context: Context,
    private val client: OkHttpClient,
) {
    /**
     * Lädt MP3 vom Server und gibt den Pfad zur Temp-Datei zurück.
     */
    suspend fun fetchAudio(
        serverUrl: String,
        token: String,
        text: String,
        voice: String,
    ): File = withContext(Dispatchers.IO) {
        val base = serverUrl.trimEnd('/')
        val body = JSONObject().apply {
            put("text", text)
            put("voice", voice)
        }.toString().toRequestBody("application/json".toMediaType())

        val req = Request.Builder()
            .url("$base/api/tts")
            .addHeader("Authorization", "Bearer $token")
            .post(body)
            .build()

        val resp = client.newBuilder()
            .callTimeout(20, java.util.concurrent.TimeUnit.SECONDS)
            .build()
            .newCall(req).execute()

        if (!resp.isSuccessful) {
            val msg = resp.body?.string() ?: resp.code.toString()
            throw Exception("TTS ${resp.code}: $msg")
        }
        val bytes = resp.body?.bytes() ?: throw Exception("Leere Antwort")
        val tmp = File(context.cacheDir, "tts_${System.currentTimeMillis()}.mp3")
        tmp.writeBytes(bytes)
        Log.d(TAG, "Audio: ${bytes.size} B → ${tmp.name}")
        tmp
    }

    /**
     * Lädt verfügbare Stimmen vom Server.
     */
    suspend fun fetchVoices(
        serverUrl: String,
        token: String,
        locale: String = "de-",
    ): List<ServerVoice> = withContext(Dispatchers.IO) {
        val base = serverUrl.trimEnd('/')
        val req = Request.Builder()
            .url("$base/api/tts/voices?locale=$locale")
            .addHeader("Authorization", "Bearer $token")
            .get()
            .build()

        val resp = client.newCall(req).execute()
        if (!resp.isSuccessful) return@withContext emptyList()
        val json = resp.body?.string() ?: return@withContext emptyList()
        val arr = JSONArray(json)
        (0 until arr.length()).map { i ->
            val o = arr.getJSONObject(i)
            ServerVoice(
                name    = o.getString("name"),
                gender  = o.optString("gender", ""),
                locale  = o.optString("locale", ""),
                display = o.optString("display", o.getString("name")),
            )
        }
    }
}

data class ServerVoice(
    val name: String,
    val gender: String,
    val locale: String,
    val display: String,
)
