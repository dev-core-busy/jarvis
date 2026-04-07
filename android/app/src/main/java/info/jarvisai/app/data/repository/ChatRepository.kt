package info.jarvisai.app.data.repository

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import info.jarvisai.app.data.api.JarvisWebSocket
import info.jarvisai.app.desktop.AndroidDesktopExecutor
import info.jarvisai.app.data.model.AgentInfo
import info.jarvisai.app.data.model.ChatMessage
import info.jarvisai.app.data.model.ConnectionState
import info.jarvisai.app.data.model.MessageRole
import info.jarvisai.app.data.model.MessageSegment
import info.jarvisai.app.data.model.SegmentType
import info.jarvisai.app.data.model.WsEvent
import info.jarvisai.app.data.prefs.SettingsDataStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.io.File
import java.util.UUID
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

    private val desktopExecutor = AndroidDesktopExecutor(context)

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages

    // ID der aktuell streamenden Jarvis-Nachricht (null = keine)
    private var streamingMsgId: String? = null

    // STATUS-Segmente die vor der ersten Antwort gepuffert werden
    private val pendingStatus = mutableListOf<MessageSegment>()

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
        // Laufenden Stream + Puffer abschliessen bevor neue Anfrage gesendet wird
        pendingStatus.clear()
        finalizeStream()
        val userMsg = ChatMessage(role = MessageRole.USER, text = text)
        _messages.update { it + userMsg }
        ws.sendTask(text)
        saveMessages()
    }

    private suspend fun collectEvents() {
        ws.events.collect { event -> handleEvent(event) }
    }

    private suspend fun collectDesktopCommands() {
        ws.desktopCommands.collect { event ->
            val (output, error, exitCode) = desktopExecutor.execute(event)
            ws.sendDesktopResult(event.request_id, event.action, output, error, exitCode)
        }
    }

    private fun handleEvent(event: WsEvent) {
        when (event.type) {
            // highlight=false → Statuszeile versteckt
            // highlight=true + beginnt mit ⏳ → Wartemeldung, ebenfalls versteckt
            // highlight=true + sonstiger Text → eigentliche LLM-Antwort, sichtbar
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
                _messages.update {
                    it + ChatMessage(
                        role = MessageRole.JARVIS,
                        text = "Fehler: ${event.message}",
                        segments = listOf(MessageSegment(SegmentType.ANSWER, "Fehler: ${event.message}")),
                    )
                }
                saveMessages()
            }
            "agent_event" -> {
                when (event.event) {
                    "finished" -> finalizeStream()
                    else -> { /* started/spawned – kein Chat-Text nötig */ }
                }
            }
            "ping", "cpu", "agent_list" -> { /* ignorieren */ }
        }
    }

    private fun appendToStream(text: String, type: SegmentType) {
        if (text.isBlank()) return
        val segment = MessageSegment(type = type, text = text)
        val id = streamingMsgId

        if (id == null) {
            if (type == SegmentType.STATUS) {
                // STATUS vor erster Antwort puffern – noch keine sichtbare Bubble erstellen
                pendingStatus.add(segment)
                return
            }
            // Erste ANSWER: Bubble mit allen gepufferten STATUS-Segmenten + ANSWER erstellen
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
            // Segment zur bestehenden Streaming-Nachricht hinzufügen
            _messages.update { msgs ->
                msgs.map { msg ->
                    if (msg.id == id) msg.copy(
                        text = msg.text + "\n" + text,
                        segments = msg.segments + segment,
                    ) else msg
                }
            }
        }
    }

    private fun finalizeStream() {
        pendingStatus.clear() // Post-run STATUS-Events (✅ etc.) verwerfen
        val id = streamingMsgId ?: return
        streamingMsgId = null
        _messages.update { msgs ->
            msgs.map { msg ->
                if (msg.id == id) msg.copy(isStreaming = false) else msg
            }
        }
        saveMessages()
    }

    fun deleteMessages(ids: Set<String>) {
        _messages.update { msgs -> msgs.filter { it.id !in ids } }
        saveMessages()
    }

    fun clearMessages() {
        _messages.update { emptyList() }
        runCatching { msgFile.delete() }
    }

    // ── Disk-Persistenz ───────────────────────────────────────────────

    private fun saveMessages() {
        scope.launch(Dispatchers.IO) {
            runCatching {
                val data = json.encodeToString(
                    ListSerializer(ChatMessage.serializer()),
                    _messages.value.takeLast(100),
                )
                msgFile.writeText(data)
            }
        }
    }

    private fun loadMessages() {
        runCatching {
            if (msgFile.exists()) {
                val msgs = json.decodeFromString(
                    ListSerializer(ChatMessage.serializer()),
                    msgFile.readText(),
                )
                // Altes Format (vor Segment-Einführung): Jarvis-Nachrichten ohne Segmente
                // haben rohen Text mit Status-Zeilen – verwerfen und neu beginnen
                val isLegacyFormat = msgs.any {
                    it.role == MessageRole.JARVIS && it.segments.isEmpty() && it.text.isNotBlank()
                }
                if (isLegacyFormat) {
                    msgFile.delete()
                    return
                }
                // isStreaming-Flag beim Laden immer zurücksetzen (App-Neustart)
                _messages.value = msgs.map { it.copy(isStreaming = false) }
            }
        }
    }
}
