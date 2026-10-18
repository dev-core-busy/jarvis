package info.jarvisai.app.ui.chat

import info.jarvisai.app.data.tls.ServerVertrauen
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
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
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

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

// Zertifikat: System/Firmen-CA oder bestaetigt (BSI M11, ServerVertrauen)
private val bildClient: OkHttpClient by lazy {
    ServerVertrauen.anwenden(OkHttpClient.Builder()).build()
}

// Code-Review 2026-10-18: kleiner Speicher-Cache fuer bereits dekodierte Bilder,
// damit Scrollen im Chat nicht jedes Mal neu laedt und dekodiert. Groesse in Byte,
// ein Sechzehntel des App-Heaps.
private val bildCache = object : LruCache<String, Bitmap>(
    (Runtime.getRuntime().maxMemory() / 16).coerceAtMost(Int.MAX_VALUE.toLong()).toInt()
) {
    override fun sizeOf(key: String, value: Bitmap): Int = value.allocationByteCount
}

// Obergrenze fuer die herunterzuladende Bilddatei (Schutz vor Speicherueberlauf)
private const val BILD_MAX_BYTES = 20L * 1024 * 1024

/**
 * Code-Review 2026-10-18: frueher wurde das Bild in voller Aufloesung dekodiert
 * (ein 4000x3000-Bild = 48 MB im Speicher, mehrere davon -> OutOfMemoryError).
 * Jetzt erst nur die Masse lesen (inJustDecodeBounds), dann mit inSampleSize
 * (Zweierpotenz) auf etwa die Anzeigegroesse verkleinert dekodieren.
 */
internal fun dekodiereVerkleinert(bytes: ByteArray, zielBreite: Int, zielHoehe: Int): Bitmap? {
    val masse = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, masse)
    if (masse.outWidth <= 0 || masse.outHeight <= 0) return null
    var stichprobe = 1
    while (masse.outWidth / (stichprobe * 2) >= zielBreite &&
        masse.outHeight / (stichprobe * 2) >= zielHoehe) {
        stichprobe *= 2
    }
    val opt = BitmapFactory.Options().apply { inSampleSize = stichprobe }
    return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opt)
}

/** Laedt ein generiertes/gesuchtes Bild vom Server und zeigt es inline an.
 *
 *  Seit 2026-10-15 verlangt der Server dafuer eine Anmeldung: das Token geht als
 *  `Authorization: Bearer` mit (vorher war die Adresse ohne Anmeldung abrufbar). */
@Composable
fun GeneratedImage(serverUrl: String, path: String, authToken: String = "") {
    // Anzeigegroesse: volle Bildschirmbreite (ContentScale.FillWidth), Hoehe als Grenze
    val konfig = LocalConfiguration.current
    val dichte = LocalDensity.current
    val zielBreite = with(dichte) { konfig.screenWidthDp.dp.roundToPx() }.coerceAtLeast(1)
    val zielHoehe = with(dichte) { konfig.screenHeightDp.dp.roundToPx() }.coerceAtLeast(1)
    val full = serverUrl.trimEnd('/') + path
    val cacheSchluessel = "$full@$zielBreite"
    var bmp by remember(cacheSchluessel) { mutableStateOf(bildCache.get(cacheSchluessel)) }
    LaunchedEffect(cacheSchluessel, authToken) {
        if (bmp != null) return@LaunchedEffect
        bmp = withContext(Dispatchers.IO) {
            try {
                val req = Request.Builder().url(full).apply {
                    if (authToken.isNotBlank()) header("Authorization", "Bearer $authToken")
                }.build()
                bildClient.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) return@withContext null
                    val body = resp.body ?: return@withContext null
                    if (body.contentLength() > BILD_MAX_BYTES) return@withContext null
                    val bytes = body.bytes()
                    dekodiereVerkleinert(bytes, zielBreite, zielHoehe)
                        ?.also { bildCache.put(cacheSchluessel, it) }
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
