package info.jarvisai.app.ui.chat

import android.app.Application
import android.app.DownloadManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import info.jarvisai.app.data.model.AgentInfo
import info.jarvisai.app.data.model.AvatarMouthState
import info.jarvisai.app.data.model.ChatMessage
import info.jarvisai.app.data.model.ConnectionState
import info.jarvisai.app.data.model.MessageRole
import info.jarvisai.app.data.model.SegmentType
import info.jarvisai.app.service.TtsManager
import info.jarvisai.app.data.prefs.DEFAULT_QUICK_ACTIONS
import info.jarvisai.app.data.prefs.SettingsDataStore
import info.jarvisai.app.data.repository.ChatRepository
import info.jarvisai.app.service.JarvisNotificationService
import info.jarvisai.app.update.DownloadPhase
import info.jarvisai.app.update.UpdateChecker
import info.jarvisai.app.update.UpdateState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
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
    private val updateChecker: UpdateChecker,
    private val ttsManager: TtsManager,
) : AndroidViewModel(application) {

    val messages: StateFlow<List<ChatMessage>> = repo.messages
    val connectionState: StateFlow<ConnectionState> = repo.connectionState
    val agents: StateFlow<List<AgentInfo>> = repo.agents
    val settings = settingsDataStore.settings

    // Avatar / TTS
    val isSpeaking: StateFlow<Boolean> = ttsManager.isSpeaking
    val avatarMouthState: StateFlow<AvatarMouthState> = ttsManager.mouthState

    private val _inputText = MutableStateFlow("")
    val inputText: StateFlow<String> = _inputText

    private val _voiceState = MutableStateFlow(VoiceState.IDLE)
    val voiceState: StateFlow<VoiceState> = _voiceState

    private val _quickActions = MutableStateFlow(DEFAULT_QUICK_ACTIONS)
    val quickActions: StateFlow<List<String>> = _quickActions

    private val _showAgentPanel = MutableStateFlow(false)
    val showAgentPanel: StateFlow<Boolean> = _showAgentPanel

    // ─── Nachrichtenauswahl (Long-Press) ──────────────────────────────
    private val _selectionMode = MutableStateFlow(false)
    val selectionMode: StateFlow<Boolean> = _selectionMode

    private val _selectedIds = MutableStateFlow<Set<String>>(emptySet())
    val selectedIds: StateFlow<Set<String>> = _selectedIds

    private val _updateState = MutableStateFlow(UpdateState())
    val updateState: StateFlow<UpdateState> = _updateState

    private var speechRecognizer: SpeechRecognizer? = null
    private var autoSendVoice = false
    private var voiceSilenceMs = 1500
    private var avatarEnabled = true   // Spiegelt settings.avatarEnabled live
    private var lastSpokenMsgId = ""   // Verhindert doppeltes Sprechen derselben Nachricht

    init {
        // Alle Settings-Änderungen live übernehmen
        viewModelScope.launch {
            settingsDataStore.settings.collect { s ->
                _quickActions.value = s.quickActions
                autoSendVoice = s.autoSendVoice
                voiceSilenceMs = s.voiceSilenceMs
                avatarEnabled = s.avatarEnabled
                ttsManager.configure(
                    serverTtsEnabled = s.serverTtsEnabled,
                    serverUrl        = s.serverUrl,
                    apiKey           = s.apiKey,
                    serverVoice      = s.serverTtsVoice,
                    androidVoice     = s.androidTtsVoice,
                )
            }
        }
        // Fertige Jarvis-Antworten vorlesen wenn Avatar aktiv
        viewModelScope.launch {
            repo.messages.collect { msgs ->
                val last = msgs.lastOrNull() ?: return@collect
                if (last.role != MessageRole.JARVIS) return@collect
                if (last.isStreaming) return@collect
                if (last.id == lastSpokenMsgId) return@collect
                if (!avatarEnabled) return@collect
                val answerText = last.segments
                    .filter { it.type == SegmentType.ANSWER }
                    .joinToString(" ") { it.text.trim() }
                if (answerText.isBlank()) return@collect
                lastSpokenMsgId = last.id
                ttsManager.speak(answerText)
            }
        }
        // Neu verbinden nur wenn URL oder Key sich ändert
        viewModelScope.launch {
            settingsDataStore.settings
                .distinctUntilChanged { old, new ->
                    old.serverUrl == new.serverUrl && old.apiKey == new.apiKey
                }
                .collectLatest { settings ->
                    if (settings.serverUrl.isNotBlank() && settings.apiKey.isNotBlank()) {
                        repo.connect()
                    }
                }
        }
        // Update-Check beim Start
        viewModelScope.launch {
            _updateState.value = updateChecker.check()
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
        ttsManager.stop()   // Laufende Sprachausgabe unterbrechen
        repo.sendMessage(text)
    }

    fun sendQuickAction(action: String) {
        ttsManager.stop()
        repo.sendMessage(action)
    }

    fun toggleAgentPanel() { _showAgentPanel.value = !_showAgentPanel.value }

    fun enterSelectionMode(msgId: String) {
        _selectionMode.value = true
        _selectedIds.value = setOf(msgId)
    }

    fun toggleSelection(msgId: String) {
        val ids = _selectedIds.value
        _selectedIds.value = if (msgId in ids) ids - msgId else ids + msgId
        if (_selectedIds.value.isEmpty()) _selectionMode.value = false
    }

    fun selectAll() {
        val allIds = messages.value.map { it.id }.toSet()
        _selectedIds.value = if (_selectedIds.value.size == allIds.size) emptySet() else allIds
        if (_selectedIds.value.isEmpty()) _selectionMode.value = false
    }

    fun exitSelectionMode() {
        _selectionMode.value = false
        _selectedIds.value = emptySet()
    }

    fun deleteSelected() {
        repo.deleteMessages(_selectedIds.value)
        exitSelectionMode()
    }

    fun downloadUpdate() {
        val ctx = getApplication<Application>()
        val downloadId = updateChecker.startDownload(ctx)
        _updateState.value = _updateState.value.copy(
            phase = DownloadPhase.DOWNLOADING,
            progress = 0,
            downloadId = downloadId,
        )
        viewModelScope.launch(Dispatchers.IO) {
            val dm = ctx.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            while (true) {
                val cursor = dm.query(DownloadManager.Query().setFilterById(downloadId))
                if (cursor != null && cursor.moveToFirst()) {
                    val status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
                    val downloaded = cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
                    val total = cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES))
                    cursor.close()
                    when (status) {
                        DownloadManager.STATUS_SUCCESSFUL -> {
                            _updateState.value = _updateState.value.copy(phase = DownloadPhase.READY, progress = 100)
                            break
                        }
                        DownloadManager.STATUS_FAILED -> {
                            _updateState.value = _updateState.value.copy(phase = DownloadPhase.ERROR)
                            break
                        }
                        else -> {
                            val pct = if (total > 0) (downloaded * 100 / total).toInt() else 0
                            _updateState.value = _updateState.value.copy(progress = pct)
                        }
                    }
                } else {
                    cursor?.close()
                }
                delay(500)
            }
        }
    }

    fun dismissUpdate() {
        _updateState.value = UpdateState()
    }

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
            putExtra("android.speech.extra.SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS", voiceSilenceMs.toLong())
            putExtra("android.speech.extra.SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS", voiceSilenceMs.toLong())
            putExtra("android.speech.extra.SPEECH_INPUT_MINIMUM_LENGTH_MILLIS", 500L)
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
        ttsManager.stop()
    }
}
