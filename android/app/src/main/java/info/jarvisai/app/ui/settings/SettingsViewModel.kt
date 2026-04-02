package info.jarvisai.app.ui.settings

import android.media.MediaPlayer
import android.speech.tts.Voice
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import info.jarvisai.app.data.model.AvatarType
import info.jarvisai.app.data.prefs.JarvisSettings
import info.jarvisai.app.data.prefs.SettingsDataStore
import info.jarvisai.app.service.ServerTtsPlayer
import info.jarvisai.app.service.ServerVoice
import info.jarvisai.app.service.TtsManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val store: SettingsDataStore,
    private val ttsManager: TtsManager,
    private val serverTtsPlayer: ServerTtsPlayer,
) : ViewModel() {

    private val _settings = MutableStateFlow(JarvisSettings())
    val settings: StateFlow<JarvisSettings> = _settings

    private val _saved = MutableStateFlow(false)
    val saved: StateFlow<Boolean> = _saved

    /** Android-Stimmen (de-DE, offline) */
    private val _availableVoices = MutableStateFlow<List<Voice>>(emptyList())
    val availableVoices: StateFlow<List<Voice>> = _availableVoices

    /** Server-Stimmen (edge-tts) */
    private val _serverVoices = MutableStateFlow<List<ServerVoice>>(emptyList())
    val serverVoices: StateFlow<List<ServerVoice>> = _serverVoices

    private val _serverVoicesLoading = MutableStateFlow(false)
    val serverVoicesLoading: StateFlow<Boolean> = _serverVoicesLoading

    /** Name der aktuell abgespielten Vorschau-Stimme (leer = keine) */
    private val _previewingVoice = MutableStateFlow("")
    val previewingVoice: StateFlow<String> = _previewingVoice

    private var previewPlayer: MediaPlayer? = null

    init {
        viewModelScope.launch {
            _settings.value = store.settings.first()
        }
    }

    fun loadAvailableVoices() {
        _availableVoices.value = ttsManager.getAvailableVoices()
    }

    fun loadServerVoices() {
        // Bekannte Stimmen sofort anzeigen (kein Server nötig)
        _serverVoices.value = KNOWN_EDGE_TTS_VOICES

        // Dann Server-Abfrage für aktualisierte Liste
        val s = _settings.value
        if (s.serverUrl.isBlank() || s.apiKey.isBlank()) return
        viewModelScope.launch {
            _serverVoicesLoading.value = true
            val fetched = try {
                serverTtsPlayer.fetchVoices(s.serverUrl, s.apiKey)
            } catch (_: Exception) { emptyList() }
            if (fetched.isNotEmpty()) _serverVoices.value = fetched
            _serverVoicesLoading.value = false
        }
    }

    fun previewVoice(voiceName: String) {
        val s = _settings.value
        if (s.serverUrl.isBlank() || s.apiKey.isBlank()) return
        // Läuft gerade dieselbe Stimme → stoppen
        if (_previewingVoice.value == voiceName) {
            stopPreview()
            return
        }
        stopPreview()
        _previewingVoice.value = voiceName
        viewModelScope.launch {
            try {
                val file = serverTtsPlayer.fetchAudio(
                    s.serverUrl, s.apiKey,
                    text = "Hallo, ich bin Jarvis, dein persönlicher Assistent.",
                    voice = voiceName,
                )
                previewPlayer = MediaPlayer().apply {
                    setDataSource(file.absolutePath)
                    prepare()
                    setOnCompletionListener {
                        _previewingVoice.value = ""
                        file.delete()
                    }
                    start()
                }
            } catch (_: Exception) {
                _previewingVoice.value = ""
            }
        }
    }

    private fun stopPreview() {
        previewPlayer?.runCatching { stop(); release() }
        previewPlayer = null
        _previewingVoice.value = ""
    }

    override fun onCleared() {
        super.onCleared()
        stopPreview()
    }

    fun onServerTtsEnabledChange(enabled: Boolean) {
        _settings.value = _settings.value.copy(serverTtsEnabled = enabled)
    }

    fun onServerTtsVoiceChange(voice: String) {
        _settings.value = _settings.value.copy(serverTtsVoice = voice)
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

    fun onTtsVoiceChange(voiceName: String) {
        _settings.value = _settings.value.copy(ttsVoiceName = voiceName)
    }

    fun save() {
        viewModelScope.launch {
            store.save(_settings.value)
            _saved.value = true
        }
    }

    fun resetSaved() {
        _saved.value = false
    }
}

/** Bekannte deutsche edge-tts Stimmen – immer verfügbar ohne Server-Verbindung */
private val KNOWN_EDGE_TTS_VOICES = listOf(
    ServerVoice("de-DE-ConradNeural",              "Male",   "de-DE", "de-DE Conrad (männlich)"),
    ServerVoice("de-DE-KillianNeural",             "Male",   "de-DE", "de-DE Killian (männlich)"),
    ServerVoice("de-DE-BerndNeural",               "Male",   "de-DE", "de-DE Bernd (männlich)"),
    ServerVoice("de-DE-ChristophNeural",           "Male",   "de-DE", "de-DE Christoph (männlich)"),
    ServerVoice("de-DE-KasperNeural",              "Male",   "de-DE", "de-DE Kasper (männlich)"),
    ServerVoice("de-DE-RalfNeural",                "Male",   "de-DE", "de-DE Ralf (männlich)"),
    ServerVoice("de-DE-FlorianMultilingualNeural", "Male",   "de-DE", "de-DE Florian Multilingual (männlich)"),
    ServerVoice("de-DE-KatjaNeural",               "Female", "de-DE", "de-DE Katja (weiblich)"),
    ServerVoice("de-DE-AmalaNeural",               "Female", "de-DE", "de-DE Amala (weiblich)"),
    ServerVoice("de-DE-MajaNeural",                "Female", "de-DE", "de-DE Maja (weiblich)"),
    ServerVoice("de-DE-LouisaNeural",              "Female", "de-DE", "de-DE Louisa (weiblich)"),
    ServerVoice("de-DE-SeraphinaMultilingualNeural","Female","de-DE", "de-DE Seraphina Multilingual (weiblich)"),
    ServerVoice("de-AT-JonasNeural",               "Male",   "de-AT", "de-AT Jonas / Österreich (männlich)"),
    ServerVoice("de-CH-JanNeural",                 "Male",   "de-CH", "de-CH Jan / Schweiz (männlich)"),
)
