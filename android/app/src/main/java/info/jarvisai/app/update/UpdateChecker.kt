package info.jarvisai.app.update

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import android.os.Environment
import info.jarvisai.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import javax.inject.Inject
import javax.inject.Singleton

@Serializable
data class VersionInfo(
    val version: Int = 0,       // Kurzform in version.json
    val versionCode: Int = 0,   // Langform (Fallback)
    val notes: String = "",
) {
    val effectiveCode: Int get() = if (versionCode > 0) versionCode else version
}

enum class DownloadPhase { IDLE, DOWNLOADING, READY, ERROR }

data class UpdateState(
    val available: Boolean = false,
    val versionName: String = "",
    val versionCode: Int = 0,
    val phase: DownloadPhase = DownloadPhase.IDLE,
    val progress: Int = 0,
    val downloadId: Long = -1L,
)

@Singleton
class UpdateChecker @Inject constructor(
    private val okHttpClient: OkHttpClient,
) {
    private val versionUrl = "https://jarvis-ai.info/version.json"
    val apkUrl = "https://jarvis-ai.info/jarvis.apk"
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun check(): UpdateState = withContext(Dispatchers.IO) {
        try {
            val req = Request.Builder().url(versionUrl).build()
            val body = okHttpClient.newCall(req).execute().use { it.body?.string() ?: return@withContext UpdateState() }
            val info = json.decodeFromString<VersionInfo>(body)
            if (info.effectiveCode > BuildConfig.VERSION_CODE) {
                UpdateState(available = true, versionName = info.notes.ifBlank { "v${info.effectiveCode}" }, versionCode = info.effectiveCode)
            } else {
                UpdateState()
            }
        } catch (_: Exception) {
            UpdateState()
        }
    }

    fun startDownload(context: Context): Long {
        val dm = context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        val req = DownloadManager.Request(Uri.parse(apkUrl)).apply {
            setTitle("jarvis-ai.info Update")
            setDescription("APK wird heruntergeladen…")
            setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE)
            setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "jarvis-update.apk")
            setMimeType("application/vnd.android.package-archive")
        }
        return dm.enqueue(req)
    }

    fun getDownloadUri(context: Context, downloadId: Long): Uri? {
        val dm = context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        return dm.getUriForDownloadedFile(downloadId)
    }
}
