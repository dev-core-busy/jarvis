package info.jarvisai.app.desktop

import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import info.jarvisai.app.data.model.WsEvent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

// Code-Review 2026-10-18: Grenzen fuer shell_exec (Zeit und gelesene Ausgabe).
// Das Backend wartet 30 s auf desktop_result (backend/tools/android_desktop.py);
// 25 s lassen Zeit, die Abbruchmeldung noch zurueckzuschicken.
private const val SHELL_TIMEOUT_S = 25L
private const val SHELL_MAX_BYTES = 64 * 1024

class AndroidDesktopExecutor(private val context: Context) {

    suspend fun execute(event: WsEvent): Triple<String, String, Int> =
        withContext(Dispatchers.IO) {
            // Gibt (output, error, exitCode) zurück
            try {
                when (event.action) {
                    "shell_exec" -> shellExec(event)
                    "launch_app" -> launchApp(event)
                    "open_url"   -> openUrl(event)
                    "list_apps"  -> listApps()
                    "get_info"   -> getInfo()
                    else -> Triple(
                        "",
                        "Unbekannte Aktion: '${event.action}'. Verfügbar: shell_exec, launch_app, open_url, list_apps, get_info",
                        1,
                    )
                }
            } catch (e: Exception) {
                Triple("", "Fehler: ${e.message}", 1)
            }
        }

    private fun shellExec(event: WsEvent): Triple<String, String, Int> {
        val command = event.cmd.ifBlank { event.text }
        if (command.isBlank()) return Triple("", "Kein Befehl angegeben (cmd)", 1)
        // Code-Review 2026-10-18: frueher erst stdout, dann stderr komplett gelesen
        // (Deadlock, sobald stderr die Pipe fuellt), waitFor() ohne Zeitgrenze und
        // readText() ohne Groessengrenze. Jetzt: ein gemeinsamer Strom, begrenzt
        // gelesen, mit Zeitlimit und hartem Abbruch.
        var proc: Process? = null
        return try {
            val p = ProcessBuilder("sh", "-c", command)
                .redirectErrorStream(true)
                .start()
            proc = p
            p.outputStream.close()  // keine Eingabe - Befehle, die stdin lesen, enden sofort
            // Lesen in eigenem Thread, damit das Zeitlimit auch greift, wenn der
            // Befehl nichts ausgibt und die Leseschleife blockiert.
            val puffer = java.io.ByteArrayOutputStream()
            var abgeschnitten = false
            val leser = Thread {
                try {
                    p.inputStream.use { ein ->
                        val block = ByteArray(8192)
                        while (true) {
                            val n = ein.read(block)
                            if (n < 0) break
                            val frei = SHELL_MAX_BYTES - puffer.size()
                            if (frei > 0) puffer.write(block, 0, minOf(n, frei))
                            // Weiterlesen und verwerfen, damit der Prozess nicht an
                            // einer vollen Pipe haengt.
                            if (n > frei) abgeschnitten = true
                        }
                    }
                } catch (_: java.io.IOException) {
                    // Strom nach destroyForcibly() geschlossen - Ende
                }
            }.apply { isDaemon = true; start() }

            val fertig = p.waitFor(SHELL_TIMEOUT_S, java.util.concurrent.TimeUnit.SECONDS)
            if (!fertig) p.destroyForcibly()
            leser.join(2_000)
            // Haelt ein Kindprozess die Pipe noch offen, Leser durch Schliessen loesen
            if (leser.isAlive) runCatching { p.inputStream.close() }
            val text = puffer.toString(Charsets.UTF_8.name())
            val output = buildString {
                append(text.take(8000))
                if (abgeschnitten || text.length > 8000) append("\n[Ausgabe gekuerzt]")
            }
            if (!fertig) {
                Triple(output, "Zeitlimit von $SHELL_TIMEOUT_S s ueberschritten - Befehl abgebrochen", 124)
            } else {
                Triple(output, "", p.exitValue())
            }
        } catch (e: Exception) {
            proc?.destroyForcibly()
            Triple("", "Shell-Fehler: ${e.message}", 1)
        }
    }

    private fun launchApp(event: WsEvent): Triple<String, String, Int> {
        val query = event.text.ifBlank { event.pkg }.ifBlank { event.cmd }.lowercase().trim()
        if (query.isBlank()) return Triple("", "Kein App-Name angegeben (text)", 1)

        val pm = context.packageManager
        val apps = pm.getInstalledApplications(PackageManager.GET_META_DATA)

        val match = apps.firstOrNull { it.packageName.equals(query, ignoreCase = true) }
            ?: apps.firstOrNull { pm.getApplicationLabel(it).toString().lowercase() == query }
            ?: apps.firstOrNull { pm.getApplicationLabel(it).toString().lowercase().contains(query) }
            ?: apps.firstOrNull { it.packageName.lowercase().contains(query) }

        if (match == null) {
            val suggestions = apps
                .filter { it.flags and ApplicationInfo.FLAG_SYSTEM == 0 }
                .take(20)
                .joinToString(", ") { pm.getApplicationLabel(it).toString() }
            return Triple("", "App '$query' nicht gefunden. Installierte Apps: $suggestions", 1)
        }

        val launchIntent = pm.getLaunchIntentForPackage(match.packageName)
            ?: return Triple("", "App '${pm.getApplicationLabel(match)}' hat keinen Start-Intent", 1)

        launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(launchIntent)
        return Triple("${pm.getApplicationLabel(match)} gestartet (${match.packageName})", "", 0)
    }

    private fun openUrl(event: WsEvent): Triple<String, String, Int> {
        var url = event.text.ifBlank { event.cmd }.trim()
        if (url.isBlank()) return Triple("", "Keine URL angegeben (text)", 1)
        // Schema ergänzen falls fehlend
        if (!url.startsWith("http://") && !url.startsWith("https://")) url = "https://$url"
        return try {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
            Triple("Browser geöffnet: $url", "", 0)
        } catch (e: Exception) {
            Triple("", "Browser öffnen fehlgeschlagen: ${e.message}", 1)
        }
    }

    private fun listApps(): Triple<String, String, Int> {
        val pm = context.packageManager
        val apps = pm.getInstalledApplications(PackageManager.GET_META_DATA)
        val userApps = apps
            .filter { it.flags and ApplicationInfo.FLAG_SYSTEM == 0 }
            .sortedBy { pm.getApplicationLabel(it).toString().lowercase() }
        val list = userApps.joinToString("\n") {
            "${pm.getApplicationLabel(it)} (${it.packageName})"
        }
        return Triple(list.ifBlank { "Keine User-Apps gefunden" }, "", 0)
    }

    private fun getInfo(): Triple<String, String, Int> {
        val pm = context.packageManager
        val appCount = pm.getInstalledApplications(PackageManager.GET_META_DATA)
            .count { it.flags and ApplicationInfo.FLAG_SYSTEM == 0 }
        val info = buildString {
            appendLine("Gerät:     ${Build.MANUFACTURER} ${Build.MODEL}")
            appendLine("Android:   ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
            appendLine("Build:     ${Build.DISPLAY}")
            appendLine("CPU ABI:   ${Build.SUPPORTED_ABIS.firstOrNull() ?: "unbekannt"}")
            appendLine("User-Apps: $appCount installiert")
        }.trim()
        return Triple(info, "", 0)
    }
}
