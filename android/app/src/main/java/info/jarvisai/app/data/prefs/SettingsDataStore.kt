package info.jarvisai.app.data.prefs

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import info.jarvisai.app.data.model.AvatarType
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "jarvis_settings")

// 0 = Jarvis-Gradient (Standard), 1 = Lokales Foto, 2 = Einfarbig
const val BG_GRADIENT = 0
const val BG_PHOTO    = 1
const val BG_COLOR    = 2

// Spezial-URI für das eingebettete Jarvis-Standardbild
const val BG_DEFAULT_URI = "res://bg_jarvis"

data class JarvisSettings(
    val serverUrl: String = "",
    val apiKey: String = "",
    val autoSendVoice: Boolean = true,
    val quickActions: List<String> = DEFAULT_QUICK_ACTIONS,
    val backgroundType: Int = BG_PHOTO,
    val backgroundImageUri: String = BG_DEFAULT_URI,
    val backgroundColorArgb: Int = 0xFF0A0E17.toInt(),
    val backgroundAlpha: Float = 0.25f,
    val debugMode: Boolean = false,
    val voiceSilenceMs: Int = 800,
    val avatarType: AvatarType = AvatarType.IRONMAN,
    val serverTtsEnabled: Boolean = false,
    val serverTtsVoice: String = "de-DE-ConradNeural",
    val androidTtsVoice: String = "de-de-x-deb-network",
    val domainUsername: String = "",
    val ttsEnabled: Boolean = true,   // Sprachausgabe global an/aus
    // domainPassword wird NICHT gespeichert (Sicherheit)
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
    private val KEY_SERVER_URL    = stringPreferencesKey("server_url")
    private val KEY_API_KEY       = stringPreferencesKey("api_key")
    private val KEY_AUTO_SEND     = booleanPreferencesKey("auto_send_voice")
    private val KEY_QUICK_ACTIONS = stringPreferencesKey("quick_actions")
    private val KEY_BG_TYPE       = intPreferencesKey("bg_type")
    private val KEY_BG_IMAGE_URI  = stringPreferencesKey("bg_image_uri")
    private val KEY_BG_COLOR      = intPreferencesKey("bg_color")
    private val KEY_BG_ALPHA      = floatPreferencesKey("bg_alpha")
    private val KEY_DEBUG_MODE    = booleanPreferencesKey("debug_mode")
    private val KEY_VOICE_SILENCE      = intPreferencesKey("voice_silence_ms")
    private val KEY_AVATAR             = booleanPreferencesKey("avatar_enabled")  // Legacy-Key
    private val KEY_AVATAR_TYPE        = stringPreferencesKey("avatar_type")
    private val KEY_SERVER_TTS_ENABLED = booleanPreferencesKey("server_tts_enabled")
    private val KEY_SERVER_TTS_VOICE   = stringPreferencesKey("server_tts_voice")
    private val KEY_ANDROID_TTS_VOICE  = stringPreferencesKey("android_tts_voice")
    private val KEY_DOMAIN_USERNAME    = stringPreferencesKey("domain_username")
    private val KEY_TTS_ENABLED        = booleanPreferencesKey("tts_enabled")

    val settings: Flow<JarvisSettings> = context.dataStore.data.map { prefs ->
        JarvisSettings(
            serverUrl = prefs[KEY_SERVER_URL] ?: "",
            apiKey    = prefs[KEY_API_KEY] ?: "",
            autoSendVoice = prefs[KEY_AUTO_SEND] ?: true,
            quickActions = prefs[KEY_QUICK_ACTIONS]
                ?.split("||")?.filter { it.isNotBlank() }
                ?: DEFAULT_QUICK_ACTIONS,
            backgroundType      = prefs[KEY_BG_TYPE] ?: BG_PHOTO,
            backgroundImageUri  = prefs[KEY_BG_IMAGE_URI] ?: BG_DEFAULT_URI,
            backgroundColorArgb = prefs[KEY_BG_COLOR] ?: 0xFF0A0E17.toInt(),
            backgroundAlpha     = prefs[KEY_BG_ALPHA] ?: 0.25f,
            debugMode           = prefs[KEY_DEBUG_MODE] ?: false,
            voiceSilenceMs = prefs[KEY_VOICE_SILENCE] ?: 800,
            avatarType     = prefs[KEY_AVATAR_TYPE]
                ?.let { runCatching { AvatarType.valueOf(it) }.getOrNull() }
                ?: if (prefs[KEY_AVATAR] == false) AvatarType.NONE else AvatarType.IRONMAN,
            serverTtsEnabled    = prefs[KEY_SERVER_TTS_ENABLED] ?: false,
            serverTtsVoice      = prefs[KEY_SERVER_TTS_VOICE] ?: "de-DE-ConradNeural",
            androidTtsVoice     = prefs[KEY_ANDROID_TTS_VOICE] ?: "de-de-x-deb-network",
            domainUsername      = prefs[KEY_DOMAIN_USERNAME] ?: "",
            ttsEnabled          = prefs[KEY_TTS_ENABLED] ?: true,
        )
    }

    suspend fun save(settings: JarvisSettings) {
        context.dataStore.edit { prefs ->
            val url = settings.serverUrl.trimEnd('/').let {
                if (it.isNotBlank() && !it.startsWith("http")) "https://$it" else it
            }
            prefs[KEY_SERVER_URL]    = url
            prefs[KEY_API_KEY]       = settings.apiKey
            prefs[KEY_AUTO_SEND]     = settings.autoSendVoice
            prefs[KEY_QUICK_ACTIONS] = settings.quickActions.joinToString("||")
            prefs[KEY_BG_TYPE]       = settings.backgroundType
            prefs[KEY_BG_IMAGE_URI]  = settings.backgroundImageUri
            prefs[KEY_BG_COLOR]      = settings.backgroundColorArgb
            prefs[KEY_BG_ALPHA]      = settings.backgroundAlpha
            prefs[KEY_DEBUG_MODE]    = settings.debugMode
            prefs[KEY_VOICE_SILENCE]      = settings.voiceSilenceMs
            prefs[KEY_AVATAR_TYPE]        = settings.avatarType.name
            prefs[KEY_SERVER_TTS_ENABLED] = settings.serverTtsEnabled
            prefs[KEY_SERVER_TTS_VOICE]   = settings.serverTtsVoice
            prefs[KEY_ANDROID_TTS_VOICE]  = settings.androidTtsVoice
            prefs[KEY_DOMAIN_USERNAME]    = settings.domainUsername
            prefs[KEY_TTS_ENABLED]        = settings.ttsEnabled
        }
    }
}
