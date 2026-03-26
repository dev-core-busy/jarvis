package info.jarvisai.app.data.repository

import info.jarvisai.app.data.api.JarvisWebSocket
import info.jarvisai.app.data.model.AgentInfo
import info.jarvisai.app.data.model.ChatMessage
import info.jarvisai.app.data.model.ConnectionState
import info.jarvisai.app.data.model.MessageRole
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
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ChatRepository @Inject constructor(
    private val ws: JarvisWebSocket,
    private val settingsDataStore: SettingsDataStore,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    val connectionState: StateFlow<ConnectionState> = ws.connectionState
    val agents: StateFlow<List<AgentInfo>> = ws.agents

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages

    // ID der aktuell streamenden Jarvis-Nachricht (null = keine)
    private var streamingMsgId: String? = null

    init {
        scope.launch { collectEvents() }
    }

    suspend fun connect() {
        val settings = settingsDataStore.settings.first()
        ws.connect(settings.serverUrl, settings.apiKey)
    }

    fun disconnect() = ws.disconnect()

    fun sendMessage(text: String) {
        // User-Nachricht sofort anzeigen
        val userMsg = ChatMessage(role = MessageRole.USER, text = text)
        _messages.update { it + userMsg }
        ws.sendTask(text)
    }

    private suspend fun collectEvents() {
        ws.events.collect { event -> handleEvent(event) }
    }

    private fun handleEvent(event: WsEvent) {
        when (event.type) {
            "status" -> appendToStream(event.message)
            "highlight" -> appendToStream(event.message)
            "error" -> {
                finalizeStream()
                _messages.update {
                    it + ChatMessage(role = MessageRole.JARVIS, text = "Fehler: ${event.message}")
                }
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

    private fun appendToStream(text: String) {
        if (text.isBlank()) return
        val id = streamingMsgId
        if (id == null) {
            // Neue Streaming-Nachricht beginnen
            val newId = UUID.randomUUID().toString()
            streamingMsgId = newId
            _messages.update {
                it + ChatMessage(id = newId, role = MessageRole.JARVIS, text = text, isStreaming = true)
            }
        } else {
            // Zu bestehender Streaming-Nachricht hinzufügen
            _messages.update { msgs ->
                msgs.map { msg ->
                    if (msg.id == id) msg.copy(text = msg.text + "\n" + text) else msg
                }
            }
        }
    }

    private fun finalizeStream() {
        val id = streamingMsgId ?: return
        streamingMsgId = null
        _messages.update { msgs ->
            msgs.map { msg ->
                if (msg.id == id) msg.copy(isStreaming = false) else msg
            }
        }
    }

    fun clearMessages() = _messages.update { emptyList() }
}
