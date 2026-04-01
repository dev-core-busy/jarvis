package info.jarvisai.app.ui.settings

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

    init {
        viewModelScope.launch {
            _settings.value = store.settings.first()
        }
    }

    fun loadAvailableVoices() {
        _availableVoices.value = ttsManager.getAvailableVoices()
    }

    fun loadServerVoices() {
        val s = _settings.value
        if (s.serverUrl.isBlank() || s.apiKey.isBlank()) return
        viewModelScope.launch {
            _serverVoicesLoading.value = true
            _serverVoices.value = try {
                serverTtsPlayer.fetchVoices(s.serverUrl, s.apiKey)
            } catch (_: Exception) { emptyList() }
            _serverVoicesLoading.value = false
        }
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
