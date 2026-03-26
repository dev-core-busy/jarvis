package info.jarvisai.app.ui.chat

import android.app.Application
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import info.jarvisai.app.data.model.AgentInfo
import info.jarvisai.app.data.model.ChatMessage
import info.jarvisai.app.data.model.ConnectionState
import info.jarvisai.app.data.model.MessageRole
import info.jarvisai.app.data.prefs.DEFAULT_QUICK_ACTIONS
import info.jarvisai.app.data.prefs.SettingsDataStore
import info.jarvisai.app.data.repository.ChatRepository
import info.jarvisai.app.service.JarvisNotificationService
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import javax.inject.Inject

enum class VoiceState { IDLE, LISTENING, ERROR }

@HiltViewModel
class ChatViewModel @Inject constructor(
    application: Application,
    private val repo: ChatRepository,
    private val settingsDataStore: SettingsDataStore,
) : AndroidViewModel(application) {

    val messages: StateFlow<List<ChatMessage>> = repo.messages
    val connectionState: StateFlow<ConnectionState> = repo.connectionState
    val agents: StateFlow<List<AgentInfo>> = repo.agents

    private val _inputText = MutableStateFlow("")
    val inputText: StateFlow<String> = _inputText

    private val _voiceState = MutableStateFlow(VoiceState.IDLE)
    val voiceState: StateFlow<VoiceState> = _voiceState

    private val _quickActions = MutableStateFlow(DEFAULT_QUICK_ACTIONS)
    val quickActions: StateFlow<List<String>> = _quickActions

    private val _showAgentPanel = MutableStateFlow(false)
    val showAgentPanel: StateFlow<Boolean> = _showAgentPanel

    private var speechRecognizer: SpeechRecognizer? = null
    private var autoSendVoice = false

    init {
        // Settings beobachten: bei jeder Änderung von URL/Key neu verbinden
        viewModelScope.launch {
            settingsDataStore.settings
                .distinctUntilChanged { old, new ->
                    old.serverUrl == new.serverUrl && old.apiKey == new.apiKey
                }
                .collectLatest { settings ->
                    _quickActions.value = settings.quickActions
                    autoSendVoice = settings.autoSendVoice
                    if (settings.serverUrl.isNotBlank() && settings.apiKey.isNotBlank()) {
                        repo.connect()
                    }
                }
        }
        // Notifications wenn Agent fertig
        viewModelScope.launch {
            repo.messages.collect { msgs ->
                val last = msgs.lastOrNull()
                if (last != null && !last.isStreaming && last.role == MessageRole.JARVIS) {
                    JarvisNotificationService.showIfBackground(
                        getApplication(), last.text.take(100)
                    )
                }
            }
        }
    }

    fun onInputChange(text: String) { _inputText.value = text }

    fun sendMessage() {
        val text = _inputText.value.trim()
        if (text.isBlank()) return
        _inputText.value = ""
        repo.sendMessage(text)
    }

    fun sendQuickAction(action: String) = repo.sendMessage(action)

    fun toggleAgentPanel() { _showAgentPanel.value = !_showAgentPanel.value }

    fun reconnect() {
        viewModelScope.launch { repo.connect() }
    }

    // ─── Spracheingabe ────────────────────────────────────────────────

    fun startListening() {
        val ctx = getApplication<Application>()
        if (!SpeechRecognizer.isRecognitionAvailable(ctx)) {
            _voiceState.value = VoiceState.ERROR
            return
        }
        speechRecognizer?.destroy()
        speechRecognizer = SpeechRecognizer.createSpeechRecognizer(ctx).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    _voiceState.value = VoiceState.LISTENING
                }
                override fun onResults(results: Bundle?) {
                    val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    val text = matches?.firstOrNull() ?: ""
                    _voiceState.value = VoiceState.IDLE
                    if (text.isNotBlank()) {
                        if (autoSendVoice) {
                            repo.sendMessage(text)
                        } else {
                            _inputText.value = text
                        }
                    }
                }
                override fun onError(error: Int) { _voiceState.value = VoiceState.ERROR }
                override fun onBeginningOfSpeech() {}
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onEvent(eventType: Int, params: Bundle?) {}
                override fun onPartialResults(partialResults: Bundle?) {
                    val partial = partialResults
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull() ?: return
                    _inputText.value = partial
                }
                override fun onRmsChanged(rmsdB: Float) {}
            })
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "de-DE")
            putExtra(RecognizerIntent.EXTRA_PROMPT, "Sprich mit Jarvis…")
        }
        speechRecognizer?.startListening(intent)
    }

    fun stopListening() {
        speechRecognizer?.stopListening()
        _voiceState.value = VoiceState.IDLE
    }

    override fun onCleared() {
        super.onCleared()
        speechRecognizer?.destroy()
        speechRecognizer = null
    }
}
