package info.jarvisai.app.data.prefs

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "jarvis_settings")

data class JarvisSettings(
    val serverUrl: String = "",
    val apiKey: String = "",
    val autoSendVoice: Boolean = false,
    val quickActions: List<String> = DEFAULT_QUICK_ACTIONS,
)

val DEFAULT_QUICK_ACTIONS = listOf(
    "Screenshot machen",
    "Was läuft gerade auf dem Desktop?",
    "Wetterbericht für heute",
    "Erinnerung in 30 Minuten",
)

@Singleton
class SettingsDataStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val KEY_SERVER_URL = stringPreferencesKey("server_url")
    private val KEY_API_KEY = stringPreferencesKey("api_key")
    private val KEY_AUTO_SEND_VOICE = booleanPreferencesKey("auto_send_voice")
    private val KEY_QUICK_ACTIONS = stringPreferencesKey("quick_actions")

    val settings: Flow<JarvisSettings> = context.dataStore.data.map { prefs ->
        JarvisSettings(
            serverUrl = prefs[KEY_SERVER_URL] ?: "",
            apiKey = prefs[KEY_API_KEY] ?: "",
            autoSendVoice = prefs[KEY_AUTO_SEND_VOICE] ?: false,
            quickActions = prefs[KEY_QUICK_ACTIONS]
                ?.split("||")
                ?.filter { it.isNotBlank() }
                ?: DEFAULT_QUICK_ACTIONS,
        )
    }

    suspend fun save(settings: JarvisSettings) {
        context.dataStore.edit { prefs ->
            // https:// automatisch voranstellen wenn kein Protokoll angegeben
            val url = settings.serverUrl.trimEnd('/').let {
                if (it.isNotBlank() && !it.startsWith("http")) "https://$it" else it
            }
            prefs[KEY_SERVER_URL] = url
            prefs[KEY_API_KEY] = settings.apiKey
            prefs[KEY_AUTO_SEND_VOICE] = settings.autoSendVoice
            prefs[KEY_QUICK_ACTIONS] = settings.quickActions.joinToString("||")
        }
    }
}
