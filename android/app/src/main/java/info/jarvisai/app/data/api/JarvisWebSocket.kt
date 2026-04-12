package info.jarvisai.app.data.api

import android.util.Log
import info.jarvisai.app.data.model.AgentInfo
import info.jarvisai.app.data.model.ConnectionState
import info.jarvisai.app.data.model.WsEvent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "JarvisWS"
private const val RECONNECT_DELAY_MS = 3000L

@Serializable
private data class WsOutgoing(
    val type: String,
    val text: String,
    val token: String,
    val agent_id: String? = null,
)

@Singleton
class JarvisWebSocket @Inject constructor(
    private val client: OkHttpClient,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var ws: WebSocket? = null
    private var serverUrl: String = ""
    private var apiKey: String = ""

    private val _connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)
    val connectionState: StateFlow<ConnectionState> = _connectionState

    private val _events = MutableSharedFlow<WsEvent>(extraBufferCapacity = 64)
    val events: SharedFlow<WsEvent> = _events

    private val _desktopCommands = MutableSharedFlow<WsEvent>(extraBufferCapacity = 16)
    val desktopCommands: SharedFlow<WsEvent> = _desktopCommands

    private val _agents = MutableStateFlow<List<AgentInfo>>(emptyList())
    val agents: StateFlow<List<AgentInfo>> = _agents

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    fun connect(serverUrl: String, apiKey: String) {
        if (serverUrl.isBlank() || apiKey.isBlank()) return
        this.serverUrl = serverUrl
        this.apiKey = apiKey
        doConnect()
    }

    fun disconnect() {
        ws?.close(1000, "Manuell getrennt")
        ws = null
        _connectionState.value = ConnectionState.DISCONNECTED
    }

    fun sendTask(text: String, agentId: String = "") {
        val msg = WsOutgoing(
            type = "task",
            text = text,
            token = apiKey,
            agent_id = agentId.ifBlank { null },
        )
        val payload = json.encodeToString(msg)
        ws?.send(payload) ?: Log.w(TAG, "sendTask: WebSocket nicht verbunden")
    }

    fun sendStop(agentId: String = "") {
        val obj = buildJsonObject {
            put("type", "control")
            put("action", "stop")
            put("token", apiKey)
            if (agentId.isNotBlank()) put("agent_id", agentId)
        }
        ws?.send(obj.toString()) ?: Log.w(TAG, "sendStop: WebSocket nicht verbunden")
    }

    fun sendPing() {
        ws?.send("""{"type":"ping"}""")
    }

    fun sendDesktopResult(requestId: String, action: String, output: String, error: String = "", exitCode: Int = 0) {
        val payload = buildJsonObject {
            put("type", "desktop_result")
            put("token", apiKey)
            put("request_id", requestId)
            put("action", action)
            put("output", output)
            put("error", error)
            put("exit_code", exitCode)
        }.toString()
        ws?.send(payload) ?: Log.w(TAG, "sendDesktopResult: WebSocket nicht verbunden")
    }

    private fun buildWsUrl(url: String): String {
        val base = when {
            url.startsWith("wss://") || url.startsWith("ws://") -> url
            url.startsWith("https://") -> "wss://${url.removePrefix("https://")}"
            url.startsWith("http://")  -> "ws://${url.removePrefix("http://")}"
            else -> "wss://$url"
        }
        return if (base.endsWith("/ws")) base else "${base.trimEnd('/')}/ws"
    }

    private fun doConnect() {
        _connectionState.value = ConnectionState.CONNECTING
        val wsUrl = buildWsUrl(serverUrl)
        val request = Request.Builder().url(wsUrl).build()
        ws = client.newWebSocket(request, object : WebSocketListener() {

            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "Verbunden mit $wsUrl")
                _connectionState.value = ConnectionState.CONNECTED
                // Als Android-Client registrieren
                val reg = json.encodeToString(mapOf(
                    "type" to "register",
                    "client_type" to "android",
                    "token" to apiKey,
                ))
                webSocket.send(reg)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val event = json.decodeFromString<WsEvent>(text)
                    // Desktop-Befehle separat weiterleiten
                    if (event.type == "desktop_command") {
                        scope.launch { _desktopCommands.emit(event) }
                        return
                    }
                    scope.launch { _events.emit(event) }
                    // Agent-Liste aktualisieren
                    if (event.type == "agent_list" && event.agents.isNotEmpty()) {
                        _agents.value = event.agents
                    }
                    if (event.type == "agent_event" && event.event == "finished") {
                        _agents.value = _agents.value.map {
                            if (it.id == event.agent_id) it.copy(status = "finished") else it
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Parse-Fehler: $text", e)
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WS-Fehler: ${t.message}")
                _connectionState.value = ConnectionState.ERROR
                scheduleReconnect()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WS geschlossen: $code $reason")
                if (_connectionState.value != ConnectionState.DISCONNECTED) {
                    _connectionState.value = ConnectionState.ERROR
                    scheduleReconnect()
                }
            }
        })
    }

    private fun scheduleReconnect() {
        scope.launch {
            delay(RECONNECT_DELAY_MS)
            if (_connectionState.value != ConnectionState.CONNECTED) {
                Log.i(TAG, "Reconnect-Versuch…")
                doConnect()
            }
        }
    }
}
