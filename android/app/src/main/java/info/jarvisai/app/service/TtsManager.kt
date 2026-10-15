package info.jarvisai.app.service

import android.content.Context
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import info.jarvisai.app.data.model.AvatarMouthState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "TtsManager"

@Singleton
class TtsManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val serverTtsPlayer: ServerTtsPlayer,
) {
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private var tts: TextToSpeech? = null
    private var initialized = false
    private var pendingText: String? = null

    // Server-TTS Konfiguration (live aus Settings)
    private var serverTtsEnabled = false
    private var serverUrl = ""
    private var apiKey = ""
    private var serverVoice = "de-DE-ConradNeural"
    private var androidVoice = ""   // "" = Automatisch

    /** Konfiguration aus Settings übernehmen (wird vom ChatViewModel aufgerufen). */
    fun configure(
        serverTtsEnabled: Boolean,
        serverUrl: String,
        apiKey: String,
        serverVoice: String,
        androidVoice: String,
    ) {
        this.serverTtsEnabled = serverTtsEnabled
        this.serverUrl = serverUrl
        this.apiKey = apiKey
        this.serverVoice = serverVoice
        this.androidVoice = androidVoice
        // Android-Stimme sofort anwenden
        if (!serverTtsEnabled) applyAndroidVoice(androidVoice)
    }

    private fun applyAndroidVoice(voiceId: String) {
        if (!initialized) return
        if (voiceId.isBlank()) {
            // Automatisch: beste männliche deutsche Stimme
            val male = tts?.voices?.filter {
                it.locale.language == "de" && it.name.contains("male", ignoreCase = true)
            }?.minByOrNull { it.quality }
            if (male != null) tts?.voice = male
            else tts?.setLanguage(Locale.GERMAN)
        } else {
            val v = tts?.voices?.firstOrNull { it.name == voiceId }
            if (v != null) tts?.voice = v
        }
    }

    private val _isSpeaking = MutableStateFlow(false)
    val isSpeaking: StateFlow<Boolean> = _isSpeaking

    private val _mouthState = MutableStateFlow(AvatarMouthState.CLOSED)
    val mouthState: StateFlow<AvatarMouthState> = _mouthState

    private var mouthJob: Job? = null

    init {
        tts = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                val result = tts?.setLanguage(Locale.GERMAN)
                initialized = result != TextToSpeech.LANG_MISSING_DATA &&
                              result != TextToSpeech.LANG_NOT_SUPPORTED
                if (!initialized) {
                    Log.w(TAG, "Deutsche TTS-Stimme nicht verfügbar (result=$result)")
                } else {
                    Log.i(TAG, "TTS initialisiert (de-DE)")
                    applyAndroidVoice(androidVoice)
                    // Ausstehenden Text sprechen falls vorhanden
                    pendingText?.let { text ->
                        pendingText = null
                        speak(text)
                    }
                }
            } else {
                Log.e(TAG, "TTS-Initialisierung fehlgeschlagen (status=$status)")
            }
        }
    }

    /**
     * Text sprechen. Falls TTS noch nicht bereit, wird der Text gepuffert
     * und nach Initialisierung automatisch gesprochen.
     */
    fun speak(text: String) {
        if (text.isBlank()) return
        // Server-TTS (edge-tts)
        if (serverTtsEnabled && serverUrl.isNotBlank() && apiKey.isNotBlank()) {
            scope.launch {
                _isSpeaking.value = true
                startMouthAnimation()
                val ok = serverTtsPlayer.speak(serverUrl, apiKey, text, serverVoice)
                if (!ok) {
                    // Fallback auf Android-TTS
                    speakAndroid(text)
                } else {
                    _isSpeaking.value = false
                    stopMouthAnimation()
                }
            }
            return
        }
        speakAndroid(text)
    }

    private fun speakAndroid(text: String) {
        if (!initialized) {
            pendingText = text
            return
        }
        val utteranceId = "jarvis_${System.currentTimeMillis()}"
        tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {
                _isSpeaking.value = true
                startMouthAnimation()
            }
            override fun onDone(utteranceId: String?) {
                _isSpeaking.value = false
                stopMouthAnimation()
            }
            @Deprecated("", ReplaceWith(""))
            override fun onError(utteranceId: String?) {
                _isSpeaking.value = false
                stopMouthAnimation()
            }
        })
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, utteranceId)
    }

    /** Aktuelle Sprachausgabe sofort abbrechen */
    fun stop() {
        tts?.stop()
        _isSpeaking.value = false
        stopMouthAnimation()
    }

    /**
     * Mund-Animationsschleife: wechselt zwischen Mundpositionen
     * um Sprache zu simulieren (energie-basierte Heuristik).
     */
    private fun startMouthAnimation() {
        mouthJob?.cancel()
        mouthJob = scope.launch {
            // Unregelmäßiges Muster wirkt natürlicher als gleichmäßiger Takt
            val pattern = listOf(
                AvatarMouthState.CLOSED to 85L,
                AvatarMouthState.SMALL  to 75L,
                AvatarMouthState.OPEN   to 115L,
                AvatarMouthState.SMALL  to 70L,
                AvatarMouthState.OPEN   to 90L,
                AvatarMouthState.SMALL  to 80L,
                AvatarMouthState.CLOSED to 95L,
                AvatarMouthState.SMALL  to 65L,
                AvatarMouthState.OPEN   to 100L,
                AvatarMouthState.SMALL  to 75L,
            )
            var i = 0
            while (isActive) {
                val (state, duration) = pattern[i % pattern.size]
                _mouthState.value = state
                delay(duration)
                i++
            }
        }
    }

    private fun stopMouthAnimation() {
        mouthJob?.cancel()
        mouthJob = null
        _mouthState.value = AvatarMouthState.CLOSED
    }

    /** Testvorschau einer Android-Stimme (setzt Stimme temporär und spricht). */
    fun previewAndroidVoice(voiceId: String) {
        applyAndroidVoice(voiceId)
        speakAndroid("Hallo, ich bin Jarvis.")
    }

    /** Alle deutschen Android-TTS-Stimmen zurückgeben (id to displayName). */
    fun getAvailableAndroidVoices(): List<Pair<String, String>> =
        tts?.voices
            ?.filter { it.locale.language == "de" }
            ?.sortedBy { it.name }
            ?.map { v ->
                val g = when {
                    v.name.contains("female", ignoreCase = true) -> "♀ "
                    v.name.contains("male",   ignoreCase = true) -> "♂ "
                    else -> ""
                }
                v.name to "$g${v.name}"
            } ?: emptyList()

    fun shutdown() {
        stop()
        tts?.shutdown()
        tts = null
        scope.cancel()
    }
}
