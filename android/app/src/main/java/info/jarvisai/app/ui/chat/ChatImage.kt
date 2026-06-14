package info.jarvisai.app.ui.chat

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

// Erkennt von Jarvis erzeugte/gesuchte Bilder in der Antwort.
private val genImgUrlRe = Regex("/api/generated/[0-9a-f]{32}\\.[a-z]+")
private val genImgMdRe = Regex("!\\[[^\\]]*]\\([^)]*?/api/generated/[0-9a-f]{32}\\.[a-z]+\\)")

/** Liefert die relativen Bild-URLs und den um die Bild-Referenzen bereinigten Text. */
fun extractGenImages(text: String): Pair<List<String>, String> {
    val urls = genImgUrlRe.findAll(text).map { it.value }.toList()
    var clean = genImgMdRe.replace(text, "")
    clean = genImgUrlRe.replace(clean, "")
    return urls to clean.trim()
}

// OkHttpClient mit deaktivierter Zertifikatspruefung (self-signed Server) – analog ServerTtsPlayer.
private val trustAllClient: OkHttpClient by lazy {
    val trustAll = object : X509TrustManager {
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {}
        override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
    }
    val ssl = SSLContext.getInstance("TLS").apply {
        init(null, arrayOf<TrustManager>(trustAll), SecureRandom())
    }
    OkHttpClient.Builder()
        .sslSocketFactory(ssl.socketFactory, trustAll)
        .hostnameVerifier { _, _ -> true }
        .build()
}

/** Laedt ein generiertes/gesuchtes Bild vom Server und zeigt es inline an. */
@Composable
fun GeneratedImage(serverUrl: String, path: String) {
    var bmp by remember(path) { mutableStateOf<Bitmap?>(null) }
    LaunchedEffect(path, serverUrl) {
        bmp = withContext(Dispatchers.IO) {
            try {
                val full = serverUrl.trimEnd('/') + path
                val req = Request.Builder().url(full).build()
                trustAllClient.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) return@withContext null
                    val bytes = resp.body?.bytes() ?: return@withContext null
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                }
            } catch (e: Exception) {
                null
            }
        }
    }

    val b = bmp
    if (b != null) {
        Image(
            bitmap = b.asImageBitmap(),
            contentDescription = "Bild",
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 6.dp)
                .clip(RoundedCornerShape(10.dp)),
            contentScale = ContentScale.FillWidth,
        )
    } else {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(160.dp)
                .padding(top = 6.dp),
            contentAlignment = Alignment.Center,
        ) {
            CircularProgressIndicator(strokeWidth = 2.dp)
        }
    }
}
