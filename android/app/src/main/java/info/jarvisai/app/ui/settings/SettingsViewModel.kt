package info.jarvisai.app.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import info.jarvisai.app.data.api.ServerAdresse
import info.jarvisai.app.data.model.AvatarType
import info.jarvisai.app.data.prefs.JarvisSettings
import info.jarvisai.app.data.prefs.SettingsDataStore
import info.jarvisai.app.data.tls.ServerVertrauen
import info.jarvisai.app.service.ServerTtsPlayer
import info.jarvisai.app.service.TtsManager
import info.jarvisai.app.service.TtsVoice
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.net.URI
import javax.inject.Inject

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val store: SettingsDataStore,
    private val serverTtsPlayer: ServerTtsPlayer,
    private val ttsManager: TtsManager,
    private val httpClient: OkHttpClient,
) : ViewModel() {

    private val _settings = MutableStateFlow(JarvisSettings())
    val settings: StateFlow<JarvisSettings> = _settings

    private val _saved = MutableStateFlow(false)
    val saved: StateFlow<Boolean> = _saved

    // "" = idle, "loading", "ok", "error: ..."
    private val _loginState = MutableStateFlow("")
    val loginState: StateFlow<String> = _loginState.asStateFlow()

    private val _serverVoices = MutableStateFlow<List<TtsVoice>>(emptyList())
    val serverVoices: StateFlow<List<TtsVoice>> = _serverVoices.asStateFlow()

    private val _androidVoices = MutableStateFlow<List<Pair<String, String>>>(emptyList())
    val androidVoices: StateFlow<List<Pair<String, String>>> = _androidVoices.asStateFlow()

    private val _loadingVoices = MutableStateFlow(false)
    val loadingVoices: StateFlow<Boolean> = _loadingVoices.asStateFlow()

    /** Offene Frage "diesem Serverzertifikat vertrauen?" (BSI M11) oder null. */
    data class ZertFrage(val host: String, val fingerabdruck: String, val vorher: String?,
                         val wiederholen: () -> Unit)
    private val _zertFrage = MutableStateFlow<ZertFrage?>(null)
    val zertFrage: StateFlow<ZertFrage?> = _zertFrage.asStateFlow()

    fun zertBestaetigen() {
        val f = _zertFrage.value ?: return
        ServerVertrauen.bestaetigen(f.host, f.fingerabdruck)
        _zertFrage.value = null
        f.wiederholen()
    }

    fun zertAblehnen() {
        _zertFrage.value = null
    }

    /** Meldet e ein unbestaetigtes Zertifikat, wird gefragt statt nur ein Fehler gezeigt. */
    private fun zertFrageStellen(e: Throwable, baseUrl: String, wiederholen: () -> Unit): Boolean {
        val u = ServerVertrauen.unbekannt(e) ?: return false
        val host = runCatching { URI(baseUrl).host }.getOrNull() ?: return false
        _zertFrage.value = ZertFrage(host, u.fingerabdruck, ServerVertrauen.pinFuer(host), wiederholen)
        return true
    }

    /** Nach dem Speichern: erreicht die App den Server mit gueltigem bzw. bestaetigtem Zertifikat? */
    private fun zertifikatPruefen(serverUrl: String) {
        val base = basisUrl(serverUrl)
        if (!base.startsWith("https://")) return
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    httpClient.newCall(Request.Builder().url("$base/api/health").build()).execute().close()
                }
            } catch (e: Exception) {
                zertFrageStellen(e, base) { zertifikatPruefen(serverUrl) }
            }
        }
    }

    // Code-Review 2026-10-18: gemeinsame Umrechnung (Schema + Host + Port) statt eigener Kopie
    private fun basisUrl(serverUrl: String): String = ServerAdresse.ursprung(serverUrl)

    init {
        viewModelScope.launch {
            _settings.value = store.settings.first()
        }
    }

    fun onServerUrlChange(url: String) {
        _settings.value = _settings.value.copy(serverUrl = url)
    }

    fun onApiKeyChange(key: String) {
        _settings.value = _settings.value.copy(apiKey = key)
    }

    fun onAutoSendVoiceChange(enabled: Boolean) {
        _settings.value = _settings.value.copy(autoSendVoice = enabled)
    }

    fun onBackgroundTypeChange(type: Int) {
        _settings.value = _settings.value.copy(backgroundType = type)
    }

    fun onBackgroundImageUriChange(uri: String) {
        _settings.value = _settings.value.copy(backgroundImageUri = uri, backgroundType = 1)
    }

    fun onBackgroundColorChange(argb: Int) {
        _settings.value = _settings.value.copy(backgroundColorArgb = argb, backgroundType = 2)
    }

    fun onBackgroundAlphaChange(alpha: Float) {
        _settings.value = _settings.value.copy(backgroundAlpha = alpha)
    }

    fun onDebugModeChange(enabled: Boolean) {
        _settings.value = _settings.value.copy(debugMode = enabled)
    }

    fun onVoiceSilenceChange(ms: Int) {
        _settings.value = _settings.value.copy(voiceSilenceMs = ms)
    }

    fun onAvatarEnabledChange(enabled: Boolean) {
        _settings.value = _settings.value.copy(
            avatarType = if (enabled) AvatarType.IRONMAN else AvatarType.NONE
        )
    }

    fun onServerTtsEnabledChange(enabled: Boolean) {
        _settings.value = _settings.value.copy(serverTtsEnabled = enabled)
    }

    fun onServerTtsVoiceChange(voice: String) {
        _settings.value = _settings.value.copy(serverTtsVoice = voice)
    }

    fun onAndroidTtsVoiceChange(voice: String) {
        _settings.value = _settings.value.copy(androidTtsVoice = voice)
    }

    fun onDomainUsernameChange(username: String) {
        _settings.value = _settings.value.copy(domainUsername = username)
    }

    fun onUiLangChange(lang: String) {
        _settings.value = _settings.value.copy(uiLang = lang)
    }

    fun fetchServerVoices() {
        val s = _settings.value
        if (s.serverUrl.isBlank() || s.apiKey.isBlank()) return
        viewModelScope.launch {
            _loadingVoices.value = true
            _serverVoices.value = serverTtsPlayer.fetchVoices(s.serverUrl, s.apiKey)
            _loadingVoices.value = false
        }
    }

    fun loadAndroidVoices() {
        _androidVoices.value = ttsManager.getAvailableAndroidVoices()
    }

    fun previewAndroidVoice(voice: String) {
        ttsManager.previewAndroidVoice(voice)
    }

    fun previewServerVoice(voice: String) {
        val s = _settings.value
        if (s.serverUrl.isBlank() || s.apiKey.isBlank()) return
        viewModelScope.launch {
            serverTtsPlayer.preview(s.serverUrl, s.apiKey, voice)
        }
    }

    fun save() {
        viewModelScope.launch {
            store.save(_settings.value)
            _saved.value = true
            zertifikatPruefen(_settings.value.serverUrl)
        }
    }

    fun resetSaved() {
        _saved.value = false
    }

    fun resetLoginState() {
        _loginState.value = ""
    }

    fun loginWithCredentials(serverUrl: String, username: String, password: String) {
        viewModelScope.launch {
            _loginState.value = "loading"
            try {
                // Pfad entfernen (z.B. /ws) - nur Schema + Host + Port behalten
                val baseUrl = basisUrl(serverUrl)

                if (baseUrl.isBlank()) {
                    _loginState.value = "error: Server-URL fehlt"
                    return@launch
                }
                // "client" kennzeichnet die App: ein Admin-Konto bekommt hier eine
                // Sitzung OHNE Admin-Rechte (die App kann keinen zweiten Faktor, BSI M3).
                // Code-Review 2026-10-18: JSONObject statt Handbau - vorher wurden nur
                // Backslash und Anfuehrungszeichen maskiert, Steuerzeichen (Zeilenumbruch,
                // Tab) im Kennwort ergaben ungueltiges JSON.
                val bodyJson = JSONObject()
                    .put("username", username)
                    .put("password", password)
                    .put("client", "android")
                    .toString()
                val reqBody = bodyJson.toRequestBody("application/json".toMediaType())
                val request = Request.Builder()
                    .url("$baseUrl/api/login")
                    .post(reqBody)
                    .build()
                val responseStr = withContext(Dispatchers.IO) {
                    httpClient.newCall(request).execute().use { resp ->
                        resp.body?.string() ?: ""
                    }
                }
                val json = JSONObject(responseStr)
                if (json.getBoolean("success")) {
                    onApiKeyChange(json.getString("token"))
                    // Frischen Token SOFORT persistieren – sonst bleibt er nur im
                    // Speicher und der WebSocket (liest aus dem DataStore) verbindet
                    // weiter mit dem alten Token -> "Sitzung ungueltig/abgelaufen".
                    save()
                    _loginState.value = "ok"
                } else {
                    _loginState.value = "error: ${json.optString("error", "Anmeldung fehlgeschlagen")}"
                }
            } catch (e: Exception) {
                if (zertFrageStellen(e, basisUrl(serverUrl)) {
                        loginWithCredentials(serverUrl, username, password)
                    }) {
                    _loginState.value = ""
                } else {
                    _loginState.value = "error: ${e.message ?: "Unbekannter Fehler"}"
                }
            }
        }
    }
}
