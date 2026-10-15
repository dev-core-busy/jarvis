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
        return try {
            val proc = Runtime.getRuntime().exec(arrayOf("sh", "-c", command))
            val stdout = proc.inputStream.bufferedReader().readText()
            val stderr = proc.errorStream.bufferedReader().readText()
            val exitCode = proc.waitFor()
            val output = (stdout + if (stderr.isNotBlank()) "\n$stderr" else "").take(8000)
            Triple(output, "", exitCode)
        } catch (e: Exception) {
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
