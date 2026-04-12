package info.jarvisai.app.data.repository

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import info.jarvisai.app.data.api.JarvisWebSocket
import info.jarvisai.app.data.model.AgentInfo
import info.jarvisai.app.data.model.ChatMessage
import info.jarvisai.app.data.model.ConnectionState
import info.jarvisai.app.data.model.MessageRole
import info.jarvisai.app.data.model.MessageSegment
import info.jarvisai.app.data.model.SegmentType
import info.jarvisai.app.data.model.WsEvent
import info.jarvisai.app.data.prefs.SettingsDataStore
import info.jarvisai.app.desktop.AndroidDesktopExecutor
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.io.File
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ChatRepository @Inject constructor(
    @ApplicationContext private val context: Context,
    private val ws: JarvisWebSocket,
    private val settingsDataStore: SettingsDataStore,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }
    private val msgFile get() = File(context.filesDir, "messages.json")

    val connectionState: StateFlow<ConnectionState> = ws.connectionState
    val agents: StateFlow<List<AgentInfo>> = ws.agents

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages

    // SharedFlow für TTS-Events: KEIN Conflate – jede Antwort wird exakt einmal gesendet
    private val _speakText = MutableSharedFlow<String>(extraBufferCapacity = 5)
    val speakText: SharedFlow<String> = _speakText

    private val _isAgentRunning = MutableStateFlow(false)
    val isAgentRunning: StateFlow<Boolean> = _isAgentRunning

    // @Volatile: sicher lesbar vom Main-Thread (sendMessage) und Dispatchers.Default (handleEvent)
    @Volatile private var streamingMsgId: String? = null

    // Fallback-Timer: falls server kein agent_event:finished schickt, nach 1.5s auto-finalize
    private var finalizeTimeoutJob: Job? = null

    // CopyOnWriteArrayList: thread-sicher für gleichzeitigen Zugriff
    private val pendingStatus = CopyOnWriteArrayList<MessageSegment>()

    private val desktopExecutor = AndroidDesktopExecutor(context)

    init {
        loadMessages()
        scope.launch { collectEvents() }
        scope.launch { collectDesktopCommands() }
    }

    suspend fun connect() {
        val settings = settingsDataStore.settings.first()
        ws.connect(settings.serverUrl, settings.apiKey)
    }

    fun disconnect() = ws.disconnect()

    fun sendMessage(text: String) {
        pendingStatus.clear()
        finalizeStream()
        val userMsg = ChatMessage(role = MessageRole.USER, text = text)
        _messages.update { it + userMsg }
        _isAgentRunning.value = true
        ws.sendTask(text)
        saveMessages()
    }

    fun sendStop() {
        ws.sendStop()
    }

    private suspend fun collectEvents() {
        ws.events.collect { event ->
            try {
                handleEvent(event)
            } catch (e: Exception) {
                Log.e("ChatRepository", "handleEvent Fehler: ${e.message}", e)
            }
        }
    }

    private suspend fun collectDesktopCommands() {
        ws.desktopCommands.collect { event ->
            val (output, error, exitCode) = desktopExecutor.execute(event)
            ws.sendDesktopResult(event.request_id, event.action, output, error, exitCode)
        }
    }

    private fun handleEvent(event: WsEvent) {
        when (event.type) {
            "status" -> {
                val type = when {
                    !event.highlight                          -> SegmentType.STATUS
                    event.message.trimStart().startsWith("⏳") -> SegmentType.STATUS
                    else                                       -> SegmentType.ANSWER
                }
                appendToStream(event.message, type)
            }
            "highlight" -> appendToStream(event.message, SegmentType.ANSWER)
            "error" -> {
                finalizeStream()
                _isAgentRunning.value = false
                _messages.update {
                    it + ChatMessage(
                        role = MessageRole.JARVIS,
                        text = "Fehler: ${event.message}",
                        segments = listOf(MessageSegment(SegmentType.ANSWER, "Fehler: ${event.message}")),
                    )
                }
                saveMessages()
            }
            "llm_stats" -> {
                val sec = event.duration_ms / 1000.0
                val sb = StringBuilder("⏱ ${"%.1f".format(sec)}s")
                if (event.total_tokens > 0) {
                    sb.append(" · ${event.input_tokens} → ${event.output_tokens} Tokens")
                }
                if (event.steps > 0) {
                    sb.append(" · ${event.steps} Schritt${if (event.steps != 1) "e" else ""}")
                }
                appendToStream(sb.toString(), SegmentType.STATS)
            }
            "agent_event" -> {
                when (event.event) {
                    "finished" -> {
                        finalizeStream()
                        _isAgentRunning.value = false
                    }
                    "started" -> _isAgentRunning.value = true
                    else -> { }
                }
            }
            "ping", "cpu", "agent_list" -> { }
        }
    }

    private fun appendToStream(text: String, type: SegmentType) {
        if (text.isBlank()) return
        val segment = MessageSegment(type = type, text = text)
        val id = streamingMsgId

        if (id == null) {
            if (type == SegmentType.STATUS) {
                pendingStatus.add(segment)
                return
            }
            val newId = UUID.randomUUID().toString()
            streamingMsgId = newId
            val allSegments = pendingStatus.toList() + segment
            pendingStatus.clear()
            _messages.update {
                it + ChatMessage(
                    id = newId,
                    role = MessageRole.JARVIS,
                    text = text,
                    segments = allSegments,
                    isStreaming = true,
                )
            }
        } else {
            _messages.update { msgs ->
                msgs.map { msg ->
                    if (msg.id == id) msg.copy(
                        text = msg.text + "\n" + text,
                        segments = msg.segments + segment,
                    ) else msg
                }
            }
        }
        writeMessagesToDisk()

        // Fallback: 1.5s nach letztem Chunk auto-finalize (falls kein agent_event:finished kommt)
        finalizeTimeoutJob?.cancel()
        finalizeTimeoutJob = scope.launch {
            delay(1_500)
            if (streamingMsgId != null) {
                Log.d("ChatRepository", "finalizeStream via Timeout-Fallback")
                finalizeStream()
            }
        }
    }

    private fun finalizeStream() {
        finalizeTimeoutJob?.cancel()
        finalizeTimeoutJob = null
        pendingStatus.clear()
        val id = streamingMsgId ?: return
        streamingMsgId = null
        _messages.update { msgs ->
            msgs.map { msg ->
                if (msg.id == id) msg.copy(isStreaming = false) else msg
            }
        }
        // TTS via SharedFlow – garantiert einmalig zugestellt
        val finalMsg = _messages.value.find { it.id == id }
        val speakText = finalMsg?.segments
            ?.filter { it.type == SegmentType.ANSWER }
            ?.joinToString(" ") { it.text.trim() }
            ?.trim()
            ?.takeUnless { it.isBlank() }
            ?: finalMsg?.text?.trim()
            ?: ""
        if (speakText.isNotBlank()) {
            scope.launch { _speakText.emit(speakText) }
        }
        writeMessagesToDisk()
    }

    fun deleteMessages(ids: Set<String>) {
        _messages.update { msgs -> msgs.filter { it.id !in ids } }
        saveMessages()
    }

    fun clearMessages() {
        _messages.update { emptyList() }
        runCatching { msgFile.delete() }
    }

    private fun writeMessagesToDisk() {
        runCatching {
            val data = json.encodeToString(
                ListSerializer(ChatMessage.serializer()),
                _messages.value.takeLast(100),
            )
            msgFile.writeText(data)
        }.onFailure { e ->
            Log.e("ChatRepository", "Speichern fehlgeschlagen: ${e.message}", e)
        }
    }

    private fun saveMessages() {
        scope.launch(Dispatchers.IO) { writeMessagesToDisk() }
    }

    private fun loadMessages() {
        runCatching {
            if (msgFile.exists()) {
                val msgs = json.decodeFromString(
                    ListSerializer(ChatMessage.serializer()),
                    msgFile.readText(),
                )
                val isLegacyFormat = msgs.any {
                    it.role == MessageRole.JARVIS && it.segments.isEmpty() && it.text.isNotBlank()
                }
                if (isLegacyFormat) {
                    msgFile.delete()
                    return
                }
                _messages.value = msgs.map { it.copy(isStreaming = false) }
            }
        }
    }
}
