package info.jarvisai.app.data.prefs

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Verschluesselt den API-Schluessel der App, bevor er im DataStore landet.
 *
 * WARUM (2026-10-21): der Schluessel stand im Klartext in den Einstellungen
 * (`api_key`), und die frueher eingebundene Bibliothek security-crypto war nie
 * benutzt worden (und ist abgekuendigt). Jetzt: AES-256-GCM mit einem Schluessel
 * aus dem Android-Keystore – der verlaesst das Geraet nicht, auch nicht mit
 * Root-Zugriff auf die App-Dateien.
 *
 * Gespeichert wird `v1:` + Base64(IV 12 Byte + Chiffrat mit Pruefsumme). Der
 * Schluessel kommt ueber [schluessel] herein, damit die Logik ohne Geraet mit
 * einem Software-Schluessel pruefbar ist (SchluesselTresorTest).
 */
class SchluesselTresor(private val schluessel: () -> SecretKey) {

    /** Klartext -> gespeicherte Form. Wirft, wenn der Keystore nicht nutzbar ist. */
    fun verpacken(klartext: String): String {
        val c = Cipher.getInstance(TRANSFORMATION)
        c.init(Cipher.ENCRYPT_MODE, schluessel())
        val iv = c.iv
        val chiffrat = c.doFinal(klartext.toByteArray(Charsets.UTF_8))
        return PRAEFIX + Base64.getEncoder().encodeToString(iv + chiffrat)
    }

    /** Gespeicherte Form -> Klartext; null bei fremdem Format, Manipulation oder fehlendem Schluessel. */
    fun entpacken(wert: String): String? {
        if (!wert.startsWith(PRAEFIX)) return null
        return try {
            val roh = Base64.getDecoder().decode(wert.removePrefix(PRAEFIX))
            if (roh.size <= IV_LAENGE) return null
            val c = Cipher.getInstance(TRANSFORMATION)
            c.init(Cipher.DECRYPT_MODE, schluessel(), GCMParameterSpec(TAG_BITS, roh, 0, IV_LAENGE))
            String(c.doFinal(roh, IV_LAENGE, roh.size - IV_LAENGE), Charsets.UTF_8)
        } catch (e: Exception) {
            null
        }
    }

    companion object {
        const val PRAEFIX = "v1:"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val IV_LAENGE = 12
        private const val TAG_BITS = 128
        private const val ALIAS = "jarvis_api_schluessel"

        /** Tresor mit einem Schluessel aus dem Android-Keystore (bei Bedarf angelegt). */
        fun keystore(): SchluesselTresor = SchluesselTresor { keystoreSchluessel() }

        private fun keystoreSchluessel(): SecretKey {
            val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
            val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            gen.init(
                KeyGenParameterSpec.Builder(
                    ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
            return gen.generateKey()
        }
    }
}
