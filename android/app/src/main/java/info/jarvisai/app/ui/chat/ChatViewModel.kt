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
import android.media.MediaPlayer
import info.jarvisai.app.service.ServerTtsPlayer
import info.jarvisai.app.service.TtsManager
import info.jarvisai.app.data.prefs.DEFAULT_QUICK_ACTIONS
import info.jarvisai.app.data.prefs.SettingsDataStore
import info.jarvisai.app.data.repository.ChatRepository
import info.jarvisai.app.service.JarvisNotificationService
import info.jarvisai.app.update.DownloadPhase
import info.jarvisai.app.update.UpdateChecker
import info.jarvisai.app.update.UpdateState
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import java.io.File
import javax.inject.Inject

enum class VoiceState { IDLE, LISTENING, ERROR }

@HiltViewModel
class ChatViewModel @Inject constructor(
    application: Application,
    private val repo: ChatRepository,
    private val settingsDataStore: SettingsDataStore,
    private val updateChecker: UpdateChecker,
    private val ttsManager: TtsManager,
    private val serverTtsPlayer: ServerTtsPlayer,
) : AndroidViewModel(application) {

    val messages: StateFlow<List<ChatMessage>> = repo.messages
    val connectionState: StateFlow<ConnectionState> = repo.connectionState
    val agents: StateFlow<List<AgentInfo>> = repo.agents
    val settings = settingsDataStore.settings

    // Avatar / TTS
    val isSpeaking: StateFlow<Boolean>       = ttsManager.isSpeaking
    val avatarMouthState: StateFlow<AvatarMouthState> = ttsManager.mouthState
    val avatarType: StateFlow<info.jarvisai.app.data.model.AvatarType> get() = _avatarType

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
    private val _avatarEnabled = MutableStateFlow(true)
    private val _avatarType    = MutableStateFlow(info.jarvisai.app.data.model.AvatarType.IRONMAN)

    private var serverTtsEnabled = false
    private var serverTtsVoice   = "de-DE-ConradNeural"
    private var serverUrl        = ""
    private var apiKey           = ""
    private var mediaPlayer: MediaPlayer? = null

    // Prefetch: Audio-Download startet während LLM noch streamt
    private var prefetchJob: Deferred<File>? = null
    private var prefetchText: String = ""

    init {
        // Alle Settings-Änderungen live übernehmen
        viewModelScope.launch {
            settingsDataStore.settings.collect { s ->
                _quickActions.value = s.quickActions
                autoSendVoice    = s.autoSendVoice
                voiceSilenceMs   = s.voiceSilenceMs
                _avatarEnabled.value = s.avatarEnabled
                _avatarType.value    = s.avatarType
                serverTtsEnabled = s.serverTtsEnabled
                serverTtsVoice   = s.serverTtsVoice
                serverUrl        = s.serverUrl
                apiKey           = s.apiKey
                if (!s.serverTtsEnabled) {
                    ttsManager.setVoiceProfile(s.avatarType)
                    if (s.ttsVoiceName.isNotBlank()) ttsManager.applyVoiceName(s.ttsVoiceName)
                }
                if (!s.avatarEnabled) {
                    ttsManager.stop()
                    stopMediaPlayer()
                }
            }
        }
        // TTS über SharedFlow – kein StateFlow-Conflate, jede Antwort wird genau einmal gelesen
        viewModelScope.launch {
            repo.speakText.collect { text ->
                if (!_avatarEnabled.value) return@collect
                if (serverTtsEnabled && serverUrl.isNotBlank() && apiKey.isNotBlank()) {
                    speakViaServer(text)
                } else {
                    ttsManager.speak(text)
                }
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
        // Update-Check beim Start (Fehler ignorieren – kein Crash bei fehlender Netzverbindung)
        viewModelScope.launch {
            try {
                _updateState.value = updateChecker.check()
            } catch (e: Exception) {
                android.util.Log.w("ChatViewModel", "Update-Check fehlgeschlagen: ${e.message}")
            }
        }
        // Prefetch: Audio-Download starten wenn LLM 400ms nichts mehr schickt
        // → Fetch läuft 400ms vor Finalisierung an, hat ~1100ms Vorsprung auf den 1500ms-Timeout
        viewModelScope.launch {
            repo.messages
                .map { msgs ->
                    val msg = msgs.lastOrNull()?.takeIf { it.isStreaming && it.role == MessageRole.JARVIS }
                        ?: return@map null
                    msg.segments
                        .filter { it.type == info.jarvisai.app.data.model.SegmentType.ANSWER }
                        .joinToString(" ") { it.text.trim() }
                        .trim()
                        .ifBlank { msg.text.trim() }
                        .takeIf { it.length >= 30 }
                }
                .filterNotNull()
                .distinctUntilChanged()
                .debounce(400)               // erst nach 400ms Stille starten
                .collect { answerText ->
                    if (!serverTtsEnabled || serverUrl.isBlank() || apiKey.isBlank()) return@collect
                    if (answerText == prefetchText && prefetchJob?.isActive == true) return@collect
                    android.util.Log.d("ChatViewModel", "TTS-Prefetch startet (${answerText.length} Zeichen)")
                    prefetchJob?.cancel()
                    prefetchText = answerText
                    prefetchJob = viewModelScope.async(Dispatchers.IO) {
                        serverTtsPlayer.fetchAudio(serverUrl, apiKey, answerText, serverTtsVoice)
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

    private fun speakViaServer(text: String) {
        viewModelScope.launch(Dispatchers.IO) {
            try {
                ttsManager.startMouthAnimationPublic()
                // Prefetch nutzen wenn Text übereinstimmt ODER Prefetch-Text Anfang des finalen Texts ist
                // (LLM kann nach Prefetch-Start noch wenige Wörter hinzugefügt haben)
                val job = prefetchJob
                val prefetchUsable = job != null && !job.isCancelled &&
                    (prefetchText == text || text.startsWith(prefetchText) && (text.length - prefetchText.length) < 80)
                val file = if (prefetchUsable) {
                    android.util.Log.d("ChatViewModel", "TTS: Prefetch genutzt (${prefetchText.length}→${text.length} Zeichen)")
                    job!!.await()
                } else {
                    android.util.Log.d("ChatViewModel", "TTS: Prefetch nicht nutzbar, fetche neu")
                    prefetchJob?.cancel()
                    serverTtsPlayer.fetchAudio(serverUrl, apiKey, text, serverTtsVoice)
                }
                prefetchJob = null
                prefetchText = ""
                stopMediaPlayer()
                mediaPlayer = MediaPlayer().apply {
                    setDataSource(file.absolutePath)
                    prepare()
                    setOnCompletionListener {
                        ttsManager.stopMouthAnimationPublic()
                        file.delete()
                    }
                    start()
                }
            } catch (e: Exception) {
                android.util.Log.w("ChatViewModel", "Server-TTS fehlgeschlagen, Fallback auf Android-TTS: $e")
                ttsManager.stopMouthAnimationPublic()
                prefetchJob = null
                prefetchText = ""
                ttsManager.speak(text)
            }
        }
    }

    private fun stopMediaPlayer() {
        mediaPlayer?.runCatching { stop(); release() }
        mediaPlayer = null
    }

    override fun onCleared() {
        super.onCleared()
        speechRecognizer?.destroy()
        speechRecognizer = null
        ttsManager.stop()
        stopMediaPlayer()
    }
}
