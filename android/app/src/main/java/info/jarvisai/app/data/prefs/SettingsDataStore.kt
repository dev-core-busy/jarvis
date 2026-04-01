package info.jarvisai.app.data.prefs

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import info.jarvisai.app.data.model.AvatarType
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
    val autoSendVoice: Boolean = false,
    val quickActions: List<String> = DEFAULT_QUICK_ACTIONS,
    val backgroundType: Int = BG_PHOTO,
    val backgroundImageUri: String = BG_DEFAULT_URI,
    val backgroundColorArgb: Int = 0xFF0A0E17.toInt(),
    val backgroundAlpha: Float = 0.5f,
    val debugMode: Boolean = false,
    val voiceSilenceMs: Int = 1500,
    val avatarType: AvatarType = AvatarType.IRONMAN,
    val ttsVoiceName: String = "",          // leer = automatisch beste Stimme
) {
    /** Abwärtskompatibilität – Avatar ist aktiv wenn nicht NONE */
    val avatarEnabled: Boolean get() = avatarType != AvatarType.NONE
}

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
    private val KEY_VOICE_SILENCE = intPreferencesKey("voice_silence_ms")
    private val KEY_AVATAR        = booleanPreferencesKey("avatar_enabled")   // legacy
    private val KEY_AVATAR_TYPE   = stringPreferencesKey("avatar_type")
    private val KEY_TTS_VOICE     = stringPreferencesKey("tts_voice_name")

    val settings: Flow<JarvisSettings> = context.dataStore.data.map { prefs ->
        JarvisSettings(
            serverUrl = prefs[KEY_SERVER_URL] ?: "",
            apiKey    = prefs[KEY_API_KEY] ?: "",
            autoSendVoice = prefs[KEY_AUTO_SEND] ?: false,
            quickActions = prefs[KEY_QUICK_ACTIONS]
                ?.split("||")?.filter { it.isNotBlank() }
                ?: DEFAULT_QUICK_ACTIONS,
            backgroundType      = prefs[KEY_BG_TYPE] ?: BG_PHOTO,
            backgroundImageUri  = prefs[KEY_BG_IMAGE_URI] ?: BG_DEFAULT_URI,
            backgroundColorArgb = prefs[KEY_BG_COLOR] ?: 0xFF0A0E17.toInt(),
            backgroundAlpha     = prefs[KEY_BG_ALPHA] ?: 0.5f,
            debugMode      = prefs[KEY_DEBUG_MODE] ?: false,
            voiceSilenceMs = prefs[KEY_VOICE_SILENCE] ?: 1500,
            avatarType     = prefs[KEY_AVATAR_TYPE]
                ?.let { runCatching { AvatarType.valueOf(it) }.getOrNull() }
                ?: if (prefs[KEY_AVATAR] == false) AvatarType.NONE else AvatarType.IRONMAN,
            ttsVoiceName   = prefs[KEY_TTS_VOICE] ?: "",
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
            prefs[KEY_VOICE_SILENCE] = settings.voiceSilenceMs
            prefs[KEY_AVATAR_TYPE]   = settings.avatarType.name
            prefs[KEY_TTS_VOICE]     = settings.ttsVoiceName
        }
    }
}
