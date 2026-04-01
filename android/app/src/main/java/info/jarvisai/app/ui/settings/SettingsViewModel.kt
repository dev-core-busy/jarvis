package info.jarvisai.app.ui.settings

import android.speech.tts.Voice
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import info.jarvisai.app.data.model.AvatarType
import info.jarvisai.app.data.prefs.JarvisSettings
import info.jarvisai.app.data.prefs.SettingsDataStore
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
) : ViewModel() {

    private val _settings = MutableStateFlow(JarvisSettings())
    val settings: StateFlow<JarvisSettings> = _settings

    private val _saved = MutableStateFlow(false)
    val saved: StateFlow<Boolean> = _saved

    /** Verfügbare TTS-Stimmen (de-DE, offline) – wird beim Öffnen des Voice-Pickers geladen */
    private val _availableVoices = MutableStateFlow<List<Voice>>(emptyList())
    val availableVoices: StateFlow<List<Voice>> = _availableVoices

    init {
        viewModelScope.launch {
            _settings.value = store.settings.first()
        }
    }

    fun loadAvailableVoices() {
        _availableVoices.value = ttsManager.getAvailableVoices()
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
