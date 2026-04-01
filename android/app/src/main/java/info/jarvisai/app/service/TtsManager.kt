package info.jarvisai.app.service

import android.content.Context
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.speech.tts.Voice
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import info.jarvisai.app.data.model.AvatarMouthState
import info.jarvisai.app.data.model.AvatarType
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
) {
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private var tts: TextToSpeech? = null
    @Volatile private var initialized = false
    @Volatile private var pendingText: String? = null

    @Volatile private var speechRate  = 1.00f
    @Volatile private var speechPitch = 1.00f

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
                    // Stimmprofil anwenden (wurde ggf. schon via setVoiceProfile voreingestellt)
                    if (speechPitch != 1.00f || speechRate != 1.00f) {
                        applyIronManVoice()
                    } else {
                        tts?.setSpeechRate(speechRate)
                        tts?.setPitch(speechPitch)
                    }
                    Log.i(TAG, "TTS initialisiert (de-DE, rate=$speechRate, pitch=$speechPitch)")
                    // Engine vorwärmen: stiller Utterance → reduziert Startup-Latenz beim ersten speak()
                    tts?.speak(" ", TextToSpeech.QUEUE_FLUSH, null, "warmup")
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
     * Stimmprofil je nach Avatar-Typ anpassen.
     * IronMan: beste verfügbare männliche de-DE Offline-Stimme, falls vorhanden.
     * Pitch/Rate werden nur gesetzt wenn keine dedizierte Männer-Stimme gefunden wurde.
     */
    fun setVoiceProfile(type: AvatarType) {
        when (type) {
            AvatarType.IRONMAN -> {
                speechRate  = 1.10f
                speechPitch = 0.80f  // leicht tiefer, aber nicht blechern
                if (initialized) applyIronManVoice()
            }
            AvatarType.KARIKATUR, AvatarType.NONE -> {
                speechRate  = 1.00f
                speechPitch = 1.00f
                if (initialized) {
                    tts?.voice = null  // Standard-Stimme zurücksetzen
                    tts?.setSpeechRate(1.00f)
                    tts?.setPitch(1.00f)
                }
            }
        }
    }

    /**
     * Versucht die beste verfügbare männliche deutsche Offline-Stimme zu setzen.
     * Kriterien: de-DE, nicht netzwerkabhängig, männlich (Name enthält "male" oder "m_" o.ä.).
     * Fallback: nur Rate/Pitch anpassen wenn keine männliche Stimme verfügbar.
     */
    private fun applyIronManVoice() {
        val voices = tts?.voices ?: return
        val deLocale = Locale("de", "DE")

        // Beste männliche deutsche Offline-Stimme suchen
        val maleVoice = voices
            .filter { v ->
                !v.isNetworkConnectionRequired &&
                v.locale.language == deLocale.language &&
                (v.name.contains("male", ignoreCase = true) ||
                 v.name.contains("m_", ignoreCase = true) ||
                 v.name.contains("-m-", ignoreCase = true) ||
                 v.name.contains("_m_", ignoreCase = true))
            }
            .maxByOrNull { v ->
                when {
                    v.quality >= Voice.QUALITY_HIGH   -> 2
                    v.quality >= Voice.QUALITY_NORMAL -> 1
                    else -> 0
                }
            }

        if (maleVoice != null) {
            tts?.voice = maleVoice
            tts?.setSpeechRate(speechRate)
            tts?.setPitch(1.00f)  // Stimme ist bereits männlich, kein künstliches Pitch-Absenken
            Log.i(TAG, "Männliche Stimme: ${maleVoice.name} (quality=${maleVoice.quality})")
        } else {
            // Keine dedizierte männliche Stimme → nur Rate/Pitch
            tts?.setSpeechRate(speechRate)
            tts?.setPitch(speechPitch)
            Log.i(TAG, "Keine männliche Stimme gefunden, verwende Pitch=$speechPitch")
        }
    }

    /**
     * Text sprechen. Falls TTS noch nicht bereit, wird der Text gepuffert
     * und nach Initialisierung automatisch gesprochen.
     */
    fun speak(text: String) {
        if (text.isBlank()) return
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
            val pattern = listOf(
                AvatarMouthState.CLOSED to 180L,
                AvatarMouthState.SMALL  to 80L,
                AvatarMouthState.OPEN   to 110L,
                AvatarMouthState.SMALL  to 70L,
                AvatarMouthState.CLOSED to 220L,
                AvatarMouthState.OPEN   to 120L,
                AvatarMouthState.SMALL  to 75L,
                AvatarMouthState.CLOSED to 160L,
                AvatarMouthState.SMALL  to 65L,
                AvatarMouthState.OPEN   to 95L,
                AvatarMouthState.SMALL  to 80L,
                AvatarMouthState.CLOSED to 320L,
                AvatarMouthState.SMALL  to 70L,
                AvatarMouthState.OPEN   to 105L,
                AvatarMouthState.SMALL  to 75L,
                AvatarMouthState.CLOSED to 190L,
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

    fun shutdown() {
        stop()
        tts?.shutdown()
        tts = null
        scope.cancel()
    }
}
