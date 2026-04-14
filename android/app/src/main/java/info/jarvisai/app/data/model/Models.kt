package info.jarvisai.app.data.model

import kotlinx.serialization.Serializable

// ─── Chat ─────────────────────────────────────────────────────────────

@Serializable
enum class MessageRole { USER, JARVIS, DATE_SEPARATOR }

/** STATUS = Agenten-Statuszeile (🚀🧠⏳✅), ANSWER = eigentliche LLM-Antwort, STATS = Dauer/Token-Info */
@Serializable
enum class SegmentType { STATUS, ANSWER, STATS }

/** Mundposition des Avatars für Lip-Sync-Animation */
enum class AvatarMouthState { CLOSED, SMALL, OPEN }

/** Avatar-Typ: Iron Man Helm oder deaktiviert */
enum class AvatarType { NONE, IRONMAN }

@Serializable
data class MessageSegment(val type: SegmentType, val text: String)

@Serializable
data class ChatMessage(
    val id: String = java.util.UUID.randomUUID().toString(),
    val role: MessageRole,
    val text: String = "",                          // User-Nachricht oder Legacy-Text
    val segments: List<MessageSegment> = emptyList(), // Jarvis-Nachricht mit Styling-Info
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
    // Desktop-Steuerung
    val action: String = "",
    val request_id: String = "",
    val text: String = "",
    val cmd: String = "",
    val pkg: String = "",
    // LLM-Statistiken
    val duration_ms: Int = 0,
    val input_tokens: Int = 0,
    val output_tokens: Int = 0,
    val total_tokens: Int = 0,
    val steps: Int = 0,
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
