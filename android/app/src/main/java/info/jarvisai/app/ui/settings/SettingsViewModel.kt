package info.jarvisai.app.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import info.jarvisai.app.data.model.AvatarType
import info.jarvisai.app.data.prefs.JarvisSettings
import info.jarvisai.app.data.prefs.SettingsDataStore
import info.jarvisai.app.service.ServerTtsPlayer
import info.jarvisai.app.service.TtsManager
import info.jarvisai.app.service.TtsVoice
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val store: SettingsDataStore,
    private val serverTtsPlayer: ServerTtsPlayer,
    private val ttsManager: TtsManager,
) : ViewModel() {

    private val _settings = MutableStateFlow(JarvisSettings())
    val settings: StateFlow<JarvisSettings> = _settings

    private val _saved = MutableStateFlow(false)
    val saved: StateFlow<Boolean> = _saved

    private val _serverVoices = MutableStateFlow<List<TtsVoice>>(emptyList())
    val serverVoices: StateFlow<List<TtsVoice>> = _serverVoices.asStateFlow()

    private val _androidVoices = MutableStateFlow<List<Pair<String, String>>>(emptyList())
    val androidVoices: StateFlow<List<Pair<String, String>>> = _androidVoices.asStateFlow()

    private val _loadingVoices = MutableStateFlow(false)
    val loadingVoices: StateFlow<Boolean> = _loadingVoices.asStateFlow()

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
        }
    }

    fun resetSaved() {
        _saved.value = false
    }
}
