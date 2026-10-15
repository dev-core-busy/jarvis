package info.jarvisai.app.data.tls

import android.content.Context
import android.content.SharedPreferences
import okhttp3.OkHttpClient
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.Collections
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/**
 * Pruefung des Serverzertifikats (BSI M11, 2026-10-12).
 *
 * Bis hierher vertraute die App JEDEM Zertifikat (Trust-All + Hostname immer
 * true) – wer im Netz dazwischen sass, bekam Anmeldedaten und Sitzungstoken.
 * Jetzt gilt:
 *  1. normale Pruefung gegen den Vertrauensspeicher des Geraets (System und
 *     vom Benutzer installierte Firmen-CA, siehe network_security_config.xml),
 *     samt Rechnername/IP;
 *  2. scheitert sie (Server per IP mit eigenem Zertifikat), zaehlt nur ein
 *     ausdruecklich BESTAETIGTES Zertifikat – je Rechner gespeichert. Der
 *     Benutzer sieht beim Anmelden den Fingerabdruck (SettingsScreen); ein
 *     anderes Zertifikat am selben Rechner faellt auf.
 *
 * Die Namensbindung steckt im HostnameVerifier: der TrustManager kennt den
 * Rechner nicht und laesst ein bestaetigtes Zertifikat nur VORLAEUFIG durch;
 * erst der Verifier prueft, dass es fuer GENAU diesen Rechner bestaetigt ist.
 */
object ServerVertrauen {
    private const val PREFS = "jarvis_tls"
    private const val PRAEFIX = "pin:"

    @Volatile
    private var prefs: SharedPreferences? = null

    /** Fingerabdruecke, die der System-Vertrauensspeicher bestaetigt hat. */
    private val systemVertraut: MutableSet<String> = Collections.synchronizedSet(HashSet())

    fun init(context: Context) {
        prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    }

    fun normHost(host: String): String =
        host.trim().lowercase().removePrefix("[").removeSuffix("]")

    fun pinFuer(host: String): String? = prefs?.getString(PRAEFIX + normHost(host), null)

    /** Vom Benutzer bestaetigtes Zertifikat speichern (synchron: der Wiederholversuch folgt sofort). */
    fun bestaetigen(host: String, fingerabdruck: String) {
        prefs?.edit()?.putString(PRAEFIX + normHost(host), fingerabdruck)?.commit()
    }

    private fun allePins(): Set<String> =
        prefs?.all?.filterKeys { it.startsWith(PRAEFIX) }?.values?.mapNotNull { it as? String }?.toSet()
            ?: emptySet()

    fun fingerabdruck(cert: X509Certificate): String =
        MessageDigest.getInstance("SHA-256").digest(cert.encoded)
            .joinToString(":") { "%02X".format(it) }

    private val systemTm: X509TrustManager by lazy {
        val f = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
        f.init(null as KeyStore?)
        f.trustManagers.filterIsInstance<X509TrustManager>().first()
    }

    val trustManager: X509TrustManager = object : X509TrustManager {
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) =
            systemTm.checkClientTrusted(chain, authType)

        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            if (chain.isEmpty()) throw CertificateException("Server hat kein Zertifikat vorgelegt")
            val fp = fingerabdruck(chain[0])
            try {
                systemTm.checkServerTrusted(chain, authType)
                systemVertraut.add(fp)
            } catch (e: CertificateException) {
                // vorlaeufig: der HostnameVerifier bindet den Pin an den Rechner
                if (fp !in allePins()) throw UnbekanntesZertifikat(fp, e)
            }
        }

        override fun getAcceptedIssuers(): Array<X509Certificate> = systemTm.acceptedIssuers
    }

    val hostnameVerifier = HostnameVerifier { host, session ->
        val leaf = session.peerCertificates.firstOrNull() as? X509Certificate
            ?: return@HostnameVerifier false
        val fp = fingerabdruck(leaf)
        if (fp in systemVertraut) {
            HttpsURLConnection.getDefaultHostnameVerifier().verify(host, session)
        } else {
            pinFuer(host) == fp
        }
    }

    /** TLS-Einstellungen fuer JEDEN Client, der mit dem Jarvis-Server spricht. */
    fun anwenden(b: OkHttpClient.Builder): OkHttpClient.Builder {
        val ctx = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trustManager), null) }
        return b.sslSocketFactory(ctx.socketFactory, trustManager).hostnameVerifier(hostnameVerifier)
    }

    /** Steckt in der Fehlerkette ein unbestaetigtes Zertifikat? */
    fun unbekannt(t: Throwable?): UnbekanntesZertifikat? {
        var e = t
        var tiefe = 0
        while (e != null && tiefe < 12) {
            if (e is UnbekanntesZertifikat) return e
            e.suppressed.firstOrNull { it is UnbekanntesZertifikat }?.let { return it as UnbekanntesZertifikat }
            e = e.cause
            tiefe++
        }
        return null
    }
}

class UnbekanntesZertifikat(val fingerabdruck: String, ursache: Throwable?) :
    CertificateException("Zertifikat nicht bestätigt ($fingerabdruck)", ursache)
