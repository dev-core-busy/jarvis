package info.jarvisai.app.data.repository

import dagger.hilt.android.qualifiers.ApplicationContext
import android.content.Context
import android.util.Log
import info.jarvisai.app.data.prefs.SettingsDataStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Issue-Tracker-Repository: Spricht /api/issues an.
 * Liefert Roh-JSON-Objekte (JSONObject/JSONArray) – Mapping passiert in ViewModel/Screen.
 */
@Singleton
class IssuesRepository @Inject constructor(
    @ApplicationContext private val context: Context,
    private val httpClient: OkHttpClient,
    private val settings: SettingsDataStore,
) {
    private suspend fun baseUrl(): String {
        val s = settings.settings.first()
        val raw = s.serverUrl.trimEnd('/')
        val httpUrl = when {
            raw.startsWith("wss://") -> "https://" + raw.removePrefix("wss://")
            raw.startsWith("ws://")  -> "http://"  + raw.removePrefix("ws://")
            raw.isBlank()            -> ""
            !raw.startsWith("http")  -> "https://$raw"
            else                     -> raw
        }
        return try {
            val parsed = URI(httpUrl)
            val port = if (parsed.port > 0) ":${parsed.port}" else ""
            "${parsed.scheme}://${parsed.host}$port"
        } catch (_: Exception) { httpUrl }
    }

    private suspend fun token(): String = settings.settings.first().apiKey

    /** Aktueller User (Domain-Username aus Settings). Fuer can_edit-Check. */
    suspend fun currentUser(): String = settings.settings.first().domainUsername

    private suspend fun authBuilder(path: String): Request.Builder {
        val tok = token()
        return Request.Builder()
            .url("${baseUrl()}$path")
            .header("Authorization", "Bearer $tok")
    }

    suspend fun list(mine: Boolean = false, status: String? = null, type: String? = null): JSONArray {
        val params = mutableListOf<String>()
        if (mine) params += "mine=true"
        if (!status.isNullOrBlank()) params += "status=$status"
        if (!type.isNullOrBlank()) params += "type=$type"
        val q = if (params.isEmpty()) "" else "?" + params.joinToString("&")
        return withContext(Dispatchers.IO) {
            val req = authBuilder("/api/issues$q").get().build()
            httpClient.newCall(req).execute().use { resp ->
                val body = resp.body?.string() ?: "{}"
                if (!resp.isSuccessful) throw RuntimeException("HTTP ${resp.code}: $body")
                JSONObject(body).optJSONArray("issues") ?: JSONArray()
            }
        }
    }

    suspend fun get(id: String): JSONObject = withContext(Dispatchers.IO) {
        val req = authBuilder("/api/issues/$id").get().build()
        httpClient.newCall(req).execute().use { resp ->
            val body = resp.body?.string() ?: "{}"
            if (!resp.isSuccessful) throw RuntimeException("HTTP ${resp.code}: $body")
            JSONObject(body)
        }
    }

    suspend fun create(
        title: String, body: String, type: String, priority: String = "medium",
    ): JSONObject = withContext(Dispatchers.IO) {
        val payload = JSONObject().apply {
            put("title", title)
            put("body", body)
            put("type", type)
            put("priority", priority)
        }.toString()
        val req = authBuilder("/api/issues")
            .post(payload.toRequestBody("application/json".toMediaType()))
            .build()
        httpClient.newCall(req).execute().use { resp ->
            val raw = resp.body?.string() ?: "{}"
            if (!resp.isSuccessful) throw RuntimeException("HTTP ${resp.code}: $raw")
            JSONObject(raw)
        }
    }

    suspend fun update(id: String, patch: JSONObject): JSONObject = withContext(Dispatchers.IO) {
        val req = authBuilder("/api/issues/$id")
            .patch(patch.toString().toRequestBody("application/json".toMediaType()))
            .build()
        httpClient.newCall(req).execute().use { resp ->
            val raw = resp.body?.string() ?: "{}"
            if (!resp.isSuccessful) throw RuntimeException("HTTP ${resp.code}: $raw")
            JSONObject(raw)
        }
    }

    suspend fun delete(id: String) = withContext(Dispatchers.IO) {
        val req = authBuilder("/api/issues/$id").delete().build()
        httpClient.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) {
                val raw = resp.body?.string() ?: ""
                throw RuntimeException("HTTP ${resp.code}: $raw")
            }
        }
    }

    suspend fun uploadAttachment(id: String, filename: String, mime: String, bytes: ByteArray): JSONObject =
        withContext(Dispatchers.IO) {
            val body = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart(
                    "file", filename,
                    bytes.toRequestBody(mime.toMediaType()),
                )
                .build()
            val req = authBuilder("/api/issues/$id/attachments").post(body).build()
            httpClient.newCall(req).execute().use { resp ->
                val raw = resp.body?.string() ?: "{}"
                if (!resp.isSuccessful) throw RuntimeException("HTTP ${resp.code}: $raw")
                JSONObject(raw)
            }
        }

    /** URL eines Attachments (inkl. Token als Query-Param fuer Image-Download). */
    suspend fun attachmentUrl(id: String, name: String): String =
        "${baseUrl()}/api/issues/$id/attachments/$name?token=${token()}"

    suspend fun downloadAttachment(id: String, name: String): ByteArray = withContext(Dispatchers.IO) {
        val req = authBuilder("/api/issues/$id/attachments/$name").get().build()
        httpClient.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) throw RuntimeException("HTTP ${resp.code}")
            resp.body?.bytes() ?: ByteArray(0)
        }
    }

    companion object { private const val TAG = "IssuesRepo" }
}
