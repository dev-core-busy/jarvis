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

    // SharedFlow für TTS-Events: KEIN Conflate – jede Antwort wird exakt einmal gesendet,
    // unabhängig davon ob der Collector gerade beschäftigt ist oder andere StateFlow-Updates kommen.
    private val _speakText = MutableSharedFlow<String>(extraBufferCapacity = 5)
    val speakText: SharedFlow<String> = _speakText

    // ID der aktuell streamenden Jarvis-Nachricht (null = keine)
    // @Volatile: sicher lesbar vom Main-Thread (sendMessage) und Dispatchers.Default (handleEvent)
    @Volatile private var streamingMsgId: String? = null

    // Fallback-Timer: falls server kein agent_event:finished schickt, nach 5s auto-finalize
    private var finalizeTimeoutJob: Job? = null

    // STATUS-Segmente vor der ersten Antwort gepuffert.
    // CopyOnWriteArrayList: thread-sicher für gleichzeitigen Zugriff von Main-Thread und Default-Dispatcher
    private val pendingStatus = CopyOnWriteArrayList<MessageSegment>()

    init {
        loadMessages()
        scope.launch { collectEvents() }
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
        ws.events.collect { event ->
            try {
                handleEvent(event)
            } catch (e: Exception) {
                // Exception darf collectEvents NICHT beenden – sonst kommen keine Antworten mehr
                Log.e("ChatRepository", "handleEvent Fehler: ${e.message}", e)
            }
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
        // Synchron schreiben – läuft auf Dispatchers.Default, kein Main-Thread-Block.
        // Async-Coroutine würde bei Prozess-Kill (Wischen in Recents) nie ausgeführt.
        writeMessagesToDisk()

        // Fallback: falls server kein agent_event:finished schickt, nach 5s auto-finalize
        // Jeder neue Chunk setzt den Timer zurück – TTS feuert 5s nach letztem Segment.
        finalizeTimeoutJob?.cancel()
        finalizeTimeoutJob = scope.launch {
            delay(5_000)
            if (streamingMsgId != null) {
                Log.d("ChatRepository", "finalizeStream via 5s-Timeout-Fallback")
                finalizeStream()
            }
        }
    }

    private fun finalizeStream() {
        finalizeTimeoutJob?.cancel()
        finalizeTimeoutJob = null
        pendingStatus.clear() // Post-run STATUS-Events (✅ etc.) verwerfen
        val id = streamingMsgId ?: return
        streamingMsgId = null
        _messages.update { msgs ->
            msgs.map { msg ->
                if (msg.id == id) msg.copy(isStreaming = false) else msg
            }
        }
        // TTS-Event über SharedFlow senden – nicht conflated, wird garantiert zugestellt
        // Fallback: wenn keine ANSWER-Segmente vorhanden, gesamten Text nehmen
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
        writeMessagesToDisk() // Synchron – läuft auf Dispatchers.Default
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

    /**
     * Synchroner Schreibvorgang – darf NUR vom Dispatchers.Default/IO aufgerufen werden,
     * nie vom Main-Thread (würde UI blockieren).
     */
    private fun writeMessagesToDisk() {
        runCatching {
            val data = json.encodeToString(
                ListSerializer(ChatMessage.serializer()),
                _messages.value.takeLast(100),
            )
            msgFile.writeText(data)
        }.onFailure { e ->
            Log.e("ChatRepository", "Nachrichten speichern fehlgeschlagen: ${e.message}", e)
        }
    }

    /**
     * Asynchroner Speicheraufruf vom Main-Thread (z.B. sendMessage).
     */
    private fun saveMessages() {
        scope.launch(Dispatchers.IO) {
            writeMessagesToDisk()
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
