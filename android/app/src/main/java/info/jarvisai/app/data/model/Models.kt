package info.jarvisai.app.data.model

import kotlinx.serialization.Serializable

// ─── Chat ─────────────────────────────────────────────────────────────

enum class MessageRole { USER, JARVIS }

data class ChatMessage(
    val id: String = java.util.UUID.randomUUID().toString(),
    val role: MessageRole,
    val text: String,
    val isStreaming: Boolean = false,
    val timestamp: Long = System.currentTimeMillis(),
)

// ─── WebSocket Events (von Jarvis empfangen) ─────────────────────────

@Serializable
data class WsEvent(
    val type: String = "",
    val message: String = "",
    val highlight: Boolean = false,
    val value: Double = 0.0,          // cpu
    val agent_id: String = "",
    val label: String = "",
    val event: String = "",           // agent_event sub-type
    val agents: List<AgentInfo> = emptyList(),
)

// ─── Agent-Status ─────────────────────────────────────────────────────

@Serializable
data class AgentInfo(
    val id: String = "",
    val label: String = "",
    val is_sub_agent: Boolean = false,
    val status: String = "idle",      // idle | running | finished
)

enum class ConnectionState { DISCONNECTED, CONNECTING, CONNECTED, ERROR }
