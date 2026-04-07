package info.jarvisai.app.service

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
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.inject.Inject
import javax.inject.Singleton
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

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
    // OkHttpClient mit deaktivierter SSL-Zertifikatsprüfung (self-signed)
    private val httpClient: OkHttpClient by lazy {
        val trustAll = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {}
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
        val sslCtx = SSLContext.getInstance("TLS").apply {
            init(null, arrayOf<TrustManager>(trustAll), SecureRandom())
        }
        OkHttpClient.Builder()
            .sslSocketFactory(sslCtx.socketFactory, trustAll)
            .hostnameVerifier { _, _ -> true }
            .build()
    }

    // wss://host:port/ws → https://host:port
    private fun toHttps(wsUrl: String): String {
        var u = wsUrl.trimEnd('/').removeSuffix("/ws")
        u = u.replace("wss://", "https://").replace("ws://", "http://")
        return u
    }

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
                val resp = httpClient.newCall(req).execute()
                if (!resp.isSuccessful) {
                    Log.w(TAG, "Server TTS HTTP ${resp.code}")
                    return@withContext false
                }
                val bytes = resp.body?.bytes() ?: return@withContext false
                playMp3Bytes(bytes)
                true
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
                val resp = httpClient.newCall(req).execute()
                if (!resp.isSuccessful) return@withContext emptyList()
                val body = resp.body?.string() ?: return@withContext emptyList()
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

    private fun playMp3Bytes(data: ByteArray) {
        try {
            val tmp = File.createTempFile("jarvis_tts_", ".mp3", context.cacheDir)
            tmp.writeBytes(data)
            val mp = MediaPlayer().apply {
                setDataSource(tmp.absolutePath)
                prepare()
                setOnCompletionListener {
                    it.release()
                    tmp.delete()
                }
                start()
            }
        } catch (e: Exception) {
            Log.e(TAG, "MP3 playback error: ${e.message}")
        }
    }
}
