package info.jarvisai.app.data.api

import android.util.Log
import info.jarvisai.app.data.model.AgentInfo
import info.jarvisai.app.data.model.ConnectionState
import info.jarvisai.app.data.model.WsEvent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
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
import java.util.concurrent.atomic.AtomicInteger
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.random.Random

private const val TAG = "JarvisWS"

// Code-Review 2026-10-18: exponentieller Backoff mit Jitter statt fester 3 s -
// bei einem nicht erreichbaren Server hat jedes Geraet alle 3 s neu angeklopft,
// nach einem Server-Neustart alle gleichzeitig.
private const val RECONNECT_BASIS_MS = 1_000L
private const val RECONNECT_MAX_MS = 60_000L

// Code-Review 2026-10-18: Puffer fuer eingehende Ereignisse. Gross genug fuer
// einen gestreamten Antwortschub; ist er trotzdem voll, wird NICHT verworfen,
// sondern der Lese-Thread gebremst (siehe weiterreichen()).
private const val EREIGNIS_PUFFER = 512

@Serializable
private data class WsOutgoing(
    val type: String,
    val text: String,
    val token: String,
    val agent_id: String? = null,
    val lang: String = "de",
)

@Singleton
class JarvisWebSocket @Inject constructor(
    private val client: OkHttpClient,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    // Code-Review 2026-10-18: @Volatile, weil OkHttp-Listener, Reconnect-Coroutine
    // und Aufrufer aus der UI auf verschiedenen Threads lesen/schreiben.
    @Volatile private var ws: WebSocket? = null
    @Volatile private var serverUrl: String = ""
    @Volatile private var apiKey: String = ""

    // Code-Review 2026-10-18: jede Verbindung bekommt eine Generation. Callbacks
    // eines alten (ersetzten oder manuell getrennten) Sockets sehen eine veraltete
    // Nummer und duerfen weder den Zustand aendern noch einen Reconnect planen.
    private val generation = AtomicInteger(0)
    @Volatile private var manuellGetrennt = false
    private val fehlversuche = AtomicInteger(0)
    private var reconnectJob: Job? = null
    private val sperre = Any()

    private val _connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)
    val connectionState: StateFlow<ConnectionState> = _connectionState

    private val _events = MutableSharedFlow<WsEvent>(extraBufferCapacity = EREIGNIS_PUFFER)
    val events: SharedFlow<WsEvent> = _events

    private val _desktopCommands = MutableSharedFlow<WsEvent>(extraBufferCapacity = 64)
    val desktopCommands: SharedFlow<WsEvent> = _desktopCommands

    private val _agents = MutableStateFlow<List<AgentInfo>>(emptyList())
    val agents: StateFlow<List<AgentInfo>> = _agents

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    fun connect(serverUrl: String, apiKey: String) {
        if (serverUrl.isBlank() || apiKey.isBlank()) return
        synchronized(sperre) {
            // Bereits mit genau diesen Daten verbunden: nichts tun (z. B. neu
            // erzeugtes ViewModel) - sonst entstuende eine zweite Verbindung.
            if (ws != null && _connectionState.value == ConnectionState.CONNECTED &&
                this.serverUrl == serverUrl && this.apiKey == apiKey) return
            this.serverUrl = serverUrl
            this.apiKey = apiKey
            manuellGetrennt = false
            fehlversuche.set(0)
            reconnectJob?.cancel()
            reconnectJob = null
            verbindenGesperrt()
        }
    }

    fun disconnect() {
        synchronized(sperre) {
            // Code-Review 2026-10-18: Flag + neue Generation, damit onFailure/onClosed
            // des getrennten Sockets keinen Reconnect mehr ausloesen.
            manuellGetrennt = true
            generation.incrementAndGet()
            reconnectJob?.cancel()
            reconnectJob = null
            ws?.close(1000, "Manuell getrennt")
            ws = null
            _connectionState.value = ConnectionState.DISCONNECTED
        }
    }

    fun sendTask(text: String, agentId: String = "", lang: String = "de") {
        val msg = WsOutgoing(
            type = "task",
            text = text,
            token = apiKey,
            agent_id = agentId.ifBlank { null },
            lang = lang,
        )
        val payload = json.encodeToString(msg)
        ws?.send(payload) ?: Log.w(TAG, "sendTask: WebSocket nicht verbunden")
    }

    /**
     * Sendet eine bearbeitete User-Nachricht. Das Backend trimmt die History
     * auf die ersten [truncateUserMsgIndex] User-Nachrichten und generiert die
     * Antwort neu. [truncateUserMsgIndex] ist 0-basiert (zählt nur USER-Rollen).
     */
    fun sendTaskWithTruncate(text: String, truncateUserMsgIndex: Int, agentId: String = "", lang: String = "de") {
        val payload = buildJsonObject {
            put("type", "task")
            put("text", text)
            put("token", apiKey)
            put("lang", lang)
            put("truncate_user_msg_index", truncateUserMsgIndex)
            if (agentId.isNotBlank()) put("agent_id", agentId)
        }.toString()
        ws?.send(payload) ?: Log.w(TAG, "sendTaskWithTruncate: WebSocket nicht verbunden")
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

    /**
     * Baut eine neue Verbindung auf. Nur unter [sperre] aufrufen.
     * Code-Review 2026-10-18: ein vorhandener Socket wird vorher geschlossen -
     * frueher blieb er offen, jeder connect() ergab eine weitere Verbindung und
     * damit doppelt eintreffende Nachrichten.
     */
    private fun verbindenGesperrt() {
        val gen = generation.incrementAndGet()
        ws?.close(1000, "Neue Verbindung")
        ws = null
        _connectionState.value = ConnectionState.CONNECTING
        val wsUrl = ServerAdresse.wsAdresse(serverUrl)
        val request = Request.Builder().url(wsUrl).build()
        ws = client.newWebSocket(request, object : WebSocketListener() {

            // Gehoert dieser Callback zur aktuellen Verbindung? Abgleich ueber die
            // Generation statt ueber `webSocket === ws`, weil onOpen schon feuern
            // kann, bevor newWebSocket() zurueckkehrt und ws gesetzt ist.
            private fun aktuell(): Boolean = gen == generation.get() && !manuellGetrennt

            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (!aktuell()) {
                    webSocket.close(1000, "Veraltete Verbindung")
                    return
                }
                fehlversuche.set(0)
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
                if (!aktuell()) return
                try {
                    val event = json.decodeFromString<WsEvent>(text)
                    // Desktop-Befehle separat weiterleiten
                    if (event.type == "desktop_command") {
                        weiterreichen(_desktopCommands, event)
                        return
                    }
                    weiterreichen(_events, event)
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
                // Code-Review 2026-10-18: Fehler eines alten/getrennten Sockets ignorieren
                if (!aktuell()) return
                _connectionState.value = ConnectionState.ERROR
                scheduleReconnect(gen)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WS geschlossen: $code $reason")
                if (!aktuell()) return
                _connectionState.value = ConnectionState.ERROR
                scheduleReconnect(gen)
            }
        })
    }

    /**
     * Code-Review 2026-10-18: frueher `scope.launch { emit(event) }` pro Nachricht
     * auf Dispatchers.IO - die Coroutinen liefen parallel, gestreamte Teile und
     * "finished" konnten vertauscht ankommen. OkHttp ruft onMessage seriell auf
     * seinem Lese-Thread auf; tryEmit direkt dort haelt die Reihenfolge ein.
     * Ist der Puffer voll (Abnehmer haengt), wird NICHT still verworfen: dann
     * blockiert emit() den Lese-Thread, bis Platz ist. Das bremst nur diese eine
     * Verbindung (TCP-Gegendruck), verliert nichts und bleibt in Reihenfolge.
     */
    private fun weiterreichen(ziel: MutableSharedFlow<WsEvent>, event: WsEvent) {
        if (ziel.tryEmit(event)) return
        Log.w(TAG, "Ereignis-Puffer voll - Lese-Thread wartet auf den Abnehmer")
        runBlocking { ziel.emit(event) }
    }

    /** Plant einen Reconnect fuer Generation [gen] mit exponentiellem Backoff + Jitter. */
    private fun scheduleReconnect(gen: Int) {
        synchronized(sperre) {
            if (manuellGetrennt || gen != generation.get()) return
            reconnectJob?.cancel()
            val versuch = fehlversuche.getAndIncrement().coerceAtMost(16)
            val basis = (RECONNECT_BASIS_MS shl versuch).coerceAtMost(RECONNECT_MAX_MS)
            // Jitter: zufaellig in [basis/2, basis], damit nicht alle Geraete gleichzeitig kommen
            val warte = basis / 2 + Random.nextLong(basis / 2 + 1)
            Log.i(TAG, "Reconnect in $warte ms (Versuch ${versuch + 1})")
            reconnectJob = scope.launch {
                delay(warte)
                synchronized(sperre) {
                    if (manuellGetrennt || gen != generation.get()) return@launch
                    Log.i(TAG, "Reconnect-Versuch…")
                    verbindenGesperrt()
                }
            }
        }
    }
}
