import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.X509TrustManager;

/**
 * Minimalclient fuer die Jarvis-API: schickt Prompt + Text an den Agenten und
 * gibt dessen Antwort zurueck.
 *
 * Bewusst OHNE fremde Bibliotheken (kein Jackson/Gson), damit die Datei ohne
 * Build laeuft:
 *
 *   export JARVIS_API_KEY=...
 *   java JarvisClient.java bericht.txt
 *   java JarvisClient.java bericht.txt "Nenne nur die offenen Punkte als Liste."
 *   cat bericht.txt | java JarvisClient.java
 *
 * Endpunkt: POST /api/agent/task
 *   Auth     X-API-Key: <key>   (alternativ Authorization: Bearer <key>)
 *   Body     {"text": "...", "source": "...", "reasoning_effort": "low"}
 *   Antwort  {"success": true, "result": "..."}  bzw. {"success": false, "error": "..."}
 *
 * Der Aufruf ist synchron und zustandslos: der Server startet jeden Lauf mit
 * leerem Verlauf, aufeinanderfolgende Aufrufe beeinflussen sich also nicht.
 */
public final class JarvisClient {

    /** ECHT (Produktion). Ueber die Umgebungsvariable JARVIS_URL ueberschreibbar. */
    private static final String STANDARD_URL = "https://191.100.130.62";

    /**
     * ACHTUNG, BEWUSSTE ENTSCHEIDUNG DES BETREIBERS: keine TLS-Pruefung.
     *
     * Jarvis liefert ein selbst signiertes Zertifikat aus. Dieser Client
     * akzeptiert JEDES Zertifikat und prueft den Hostnamen NICHT – auf Wunsch,
     * weil Client und Server im selben Netz stehen. Damit ist die Verbindung
     * verschluesselt, aber NICHT gegen einen Angreifer in diesem Netz geschuetzt
     * (er koennte sich als Server ausgeben und API-Key samt Text mitlesen).
     * Wer das nicht will: das Serverzertifikat einmal abholen und nur ihm
     * vertrauen (siehe Methode nurDiesesZertifikat weiter unten).
     */
    private static final boolean TLS_PRUEFEN = false;

    static {
        // Die Hostnamen-Pruefung des JDK-HttpClient laesst sich NUR ueber diese
        // Eigenschaft abschalten, und sie muss gesetzt sein, BEVOR der Client
        // die TLS-Schicht initialisiert (deshalb hier im statischen Block und
        // nicht in main). Ohne das scheitert ein Aufruf per IP-Adresse mit
        // "No subject alternative names matching IP address ... found", obwohl
        // der TrustManager alles akzeptiert.
        if (!TLS_PRUEFEN) {
            System.setProperty("jdk.internal.httpclient.disableHostnameVerification", "true");
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // EINSTELLUNGEN FUER DEN STATISCHEN AUFRUF JarvisClient.frage(text)
    // Hier – und nur hier – werden Adresse, Schluessel und Anweisung gesetzt.
    // ─────────────────────────────────────────────────────────────────────────

    /** Zieladresse. Eine gesetzte Umgebungsvariable JARVIS_URL hat Vorrang. */
    private static final String S_URL = STANDARD_URL;

    /**
     * API-Key. Bleibt der Platzhalter stehen, wird JARVIS_API_KEY aus der
     * Umgebung genommen.
     *
     * ACHTUNG: Diese Datei liegt im Repo-Wurzelverzeichnis, und das Repo ist
     * oeffentlich. Ein hier eingetragener Schluessel wird beim naechsten Push
     * mitveroeffentlicht und muss dann als verbrannt gelten (neu generieren
     * unter Einstellungen -> Agent-API-Keys). Wer ihn hart eintraegt, sollte
     * JarvisClient.java in .gitignore aufnehmen.
     */
    private static final String S_KEY = "<HIER-API-KEY-EINTRAGEN>";

    /**
     * Anweisung fuer den statischen Aufruf.
     *
     * Sie ist so ausdruecklich formuliert, weil der Server den Text NICHT
     * unveraendert weitergibt: agent_task umhuellt ihn mit "[Externe
     * Benachrichtigung von: <source>]" und der Aufforderung, "angemessen auf die
     * Benachrichtigung zu reagieren (z.B. Begruessung, Bestaetigung)" – der
     * Endpunkt ist urspruenglich fuer Melde-Ereignisse der Vision-Kamera gebaut.
     * Ohne diese Gegenanweisung antwortet das Modell gern mit einer Bestaetigung
     * statt mit einer Zusammenfassung.
     */
    private static final String S_PROMPT =
            "Fasse den unten stehenden Text zusammen. Gib AUSSCHLIESSLICH die "
            + "Zusammenfassung aus: keine Anrede, keine Bestaetigung, keine "
            + "Rueckfrage, keine Erwaehnung dieser Anweisung. Hoechstens 5 Saetze, "
            + "sachlich, auf Deutsch. Der Text liegt vollstaendig unten vor - du "
            + "brauchst dafuer keine Werkzeuge.";

    /** Denktiefe: off|low|medium|high|max, oder null fuer die Profil-Vorgabe. */
    private static final String S_AUFWAND = "low";

    /** Einmal gebaut und wiederverwendet – ein HttpClient je Aufruf waere teuer. */
    private static volatile JarvisClient standard;

    /**
     * Fasst einen Text zusammen. Adresse, Schluessel und Anweisung stehen im
     * Block oben.
     *
     * Wirft absichtlich eine UNGEPRUEFTE Ausnahme, damit der Aufruf ein
     * Einzeiler bleibt (kein try/catch-Zwang) – verschluckt wird nichts.
     *
     *   String kurz = JarvisClient.frage(text);
     */
    public static String frage(String text) {
        return frage(text, S_PROMPT);
    }

    /** Wie {@link #frage(String)}, aber mit eigener Anweisung. */
    public static String frage(String text, String eigenerPrompt) {
        try {
            return standard().frage(eigenerPrompt, text, S_AUFWAND);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();          // Zustand nicht schlucken
            throw new JarvisFehler("Aufruf unterbrochen", e);
        } catch (Exception e) {
            throw new JarvisFehler(e.getMessage(), e);
        }
    }

    private static JarvisClient standard() throws Exception {
        JarvisClient c = standard;
        if (c == null) {
            synchronized (JarvisClient.class) {
                c = standard;
                if (c == null) {
                    String url = System.getenv().getOrDefault("JARVIS_URL", S_URL);
                    String key = S_KEY;
                    if (key.isBlank() || key.startsWith("<")) {   // Platzhalter
                        key = System.getenv("JARVIS_API_KEY");
                    }
                    standard = c = new JarvisClient(url, key);
                }
            }
        }
        return c;
    }

    /** Fehler des statischen Aufrufs – ungeprueft, mit Ursache. */
    public static final class JarvisFehler extends RuntimeException {
        private static final long serialVersionUID = 1L;
        JarvisFehler(String m, Throwable u) { super(m, u); }
    }

    private final URI endpunkt;
    private final String apiKey;
    private final HttpClient http;

    public JarvisClient(String basisUrl, String apiKey) throws Exception {
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalArgumentException(
                    "Kein API-Key. Anlegen unter Einstellungen -> Agent-API-Keys, "
                    + "dann: export JARVIS_API_KEY=...");
        }
        this.apiKey = apiKey;
        this.endpunkt = URI.create(basisUrl.replaceAll("/+$", "") + "/api/agent/task");

        HttpClient.Builder b = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .followRedirects(HttpClient.Redirect.NORMAL);
        if (!TLS_PRUEFEN) {
            b.sslContext(allesAkzeptieren());
            SSLParameters p = new SSLParameters();
            p.setEndpointIdentificationAlgorithm(null);   // wirkt nur zusammen
            b.sslParameters(p);                           // mit der Eigenschaft oben
        }
        this.http = b.build();
    }

    // ─── Aufruf ──────────────────────────────────────────────────────────────

    /**
     * Schickt Anweisung und Text in EINEM Aufruf und liefert die Antwort.
     *
     * @param prompt  die Anweisung (z.B. "Fasse in 5 Saetzen zusammen ...")
     * @param text    der zu verarbeitende Text
     * @param aufwand Denktiefe: off|low|medium|high|max, oder null fuer die
     *                Vorgabe des Profils
     */
    public String frage(String prompt, String text, String aufwand)
            throws IOException, InterruptedException {

        // Trennmarken, damit das Modell Anweisung und Nutztext sicher
        // unterscheidet - der Server haengt oben und unten noch eigenen Text an.
        String nutzlast = prompt
                + "\n\n----- TEXT ANFANG -----\n"
                + text
                + "\n----- TEXT ENDE -----";

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("text", nutzlast);
        body.put("source", "Java-Client");     // landet als api:<source> im Audit-Log
        if (aufwand != null && !aufwand.isBlank()) {
            body.put("reasoning_effort", aufwand);
        }

        HttpRequest anfrage = HttpRequest.newBuilder(endpunkt)
                // Ein Lauf kann bei langen Texten Minuten dauern (LLM). Zu kurz
                // gewaehlt bricht der Client ab, WAEHREND der Server weiterlaeuft.
                .timeout(Duration.ofMinutes(5))
                .header("Content-Type", "application/json; charset=utf-8")
                .header("X-API-Key", apiKey)
                .header("Accept", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(
                        schreibeJson(body), StandardCharsets.UTF_8))
                .build();

        HttpResponse<String> antwort = http.send(
                anfrage, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));

        Object roh;
        try {
            roh = Json.lese(antwort.body());
        } catch (RuntimeException e) {
            throw new IOException("Antwort ist kein gueltiges JSON (HTTP "
                    + antwort.statusCode() + "): " + kurz(antwort.body()), e);
        }
        if (!(roh instanceof Map)) {
            throw new IOException("Unerwartete Antwort (HTTP " + antwort.statusCode()
                    + "): " + kurz(antwort.body()));
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> d = (Map<String, Object>) roh;

        if (antwort.statusCode() != 200 || !Boolean.TRUE.equals(d.get("success"))) {
            String grund = d.get("error") instanceof String
                    ? (String) d.get("error") : kurz(antwort.body());
            if (antwort.statusCode() == 401) {
                grund += " (API-Key pruefen: Einstellungen -> Agent-API-Keys)";
            }
            throw new IOException("Jarvis HTTP " + antwort.statusCode() + ": " + grund);
        }
        Object ergebnis = d.get("result");
        return ergebnis == null ? "" : ergebnis.toString();
    }

    /**
     * Bequemer Weg fuer den Regelfall auf DIESER Instanz (eigene Adresse/eigener
     * Schluessel). Fuer den Normalfall gibt es den statischen
     * {@link #frage(String)} – der braucht keine Instanz.
     */
    public String fasseZusammen(String text) throws IOException, InterruptedException {
        return frage(S_PROMPT, text, S_AUFWAND);
    }

    // ─── TLS ─────────────────────────────────────────────────────────────────

    /** Vertraut JEDEM Zertifikat (siehe Hinweis an TLS_PRUEFEN). */
    private static SSLContext allesAkzeptieren() throws Exception {
        X509TrustManager alles = new X509TrustManager() {
            @Override public void checkClientTrusted(X509Certificate[] k, String t) { }
            @Override public void checkServerTrusted(X509Certificate[] k, String t) { }
            @Override public X509Certificate[] getAcceptedIssuers() {
                return new X509Certificate[0];
            }
        };
        SSLContext ctx = SSLContext.getInstance("TLS");
        ctx.init(null, new javax.net.ssl.TrustManager[]{alles}, new SecureRandom());
        return ctx;
    }

    /**
     * Der sichere Gegenentwurf, falls die Pruefung spaeter doch gewuenscht ist:
     * Zertifikat einmal abholen
     *   openssl s_client -connect 191.100.130.62:443 &lt;/dev/null 2&gt;/dev/null \
     *     | openssl x509 -outform DER -out jarvis.cer
     * dann TLS_PRUEFEN auf true setzen und hier den Pfad uebergeben.
     */
    @SuppressWarnings("unused")
    private static SSLContext nurDiesesZertifikat(Path cer) throws Exception {
        try (InputStream in = Files.newInputStream(cer)) {
            X509Certificate zert = (X509Certificate) java.security.cert.CertificateFactory
                    .getInstance("X.509").generateCertificate(in);
            java.security.KeyStore ks = java.security.KeyStore.getInstance(
                    java.security.KeyStore.getDefaultType());
            ks.load(null, null);
            ks.setCertificateEntry("jarvis", zert);
            javax.net.ssl.TrustManagerFactory tmf = javax.net.ssl.TrustManagerFactory
                    .getInstance(javax.net.ssl.TrustManagerFactory.getDefaultAlgorithm());
            tmf.init(ks);
            SSLContext ctx = SSLContext.getInstance("TLS");
            ctx.init(null, tmf.getTrustManagers(), null);
            return ctx;
        }
    }

    // ─── JSON schreiben ──────────────────────────────────────────────────────

    private static String schreibeJson(Map<String, Object> m) {
        StringBuilder sb = new StringBuilder("{");
        boolean erst = true;
        for (Map.Entry<String, Object> e : m.entrySet()) {
            if (!erst) sb.append(',');
            erst = false;
            sb.append('"').append(escape(e.getKey())).append("\":");
            Object v = e.getValue();
            if (v instanceof Number || v instanceof Boolean) sb.append(v);
            else if (v == null) sb.append("null");
            else sb.append('"').append(escape(v.toString())).append('"');
        }
        return sb.append('}').toString();
    }

    /** Maskiert genau die Zeichen, die in einem JSON-String verboten sind. */
    static String escape(String s) {
        StringBuilder sb = new StringBuilder(s.length() + 16);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"'  -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                case '\b' -> sb.append("\\b");
                case '\f' -> sb.append("\\f");
                default -> {
                    // Steuerzeichen muessen escaped werden; Umlaute und Emojis
                    // gehen als UTF-8 unveraendert durch (gueltiges JSON).
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
                }
            }
        }
        return sb.toString();
    }

    // ─── JSON lesen ──────────────────────────────────────────────────────────

    /**
     * Sehr kleiner, aber vollstaendiger JSON-Leser.
     *
     * Bewusst ein echter Parser und kein regulaerer Ausdruck: das Ergebnisfeld
     * enthaelt freien Modelltext, der seinerseits Anfuehrungszeichen, Zeilen-
     * umbrueche und sogar die Zeichenfolge "error": enthalten kann. Ein
     * Textsuch-Ansatz liefert dann still das falsche Feld.
     */
    static final class Json {
        private final String s;
        private int i;

        private Json(String s) { this.s = s; }

        static Object lese(String text) {
            Json j = new Json(text);
            j.leer();
            Object v = j.wert();
            j.leer();
            if (j.i < j.s.length()) throw new IllegalArgumentException(
                    "Ueberzaehlige Zeichen ab Position " + j.i);
            return v;
        }

        private Object wert() {
            if (i >= s.length()) throw new IllegalArgumentException("Unerwartetes Ende");
            char c = s.charAt(i);
            return switch (c) {
                case '{' -> objekt();
                case '[' -> liste();
                case '"' -> zeichenkette();
                default  -> einfach();
            };
        }

        private Map<String, Object> objekt() {
            Map<String, Object> m = new LinkedHashMap<>();
            i++;                       // '{'
            leer();
            if (pruefe('}')) return m;
            while (true) {
                leer();
                String k = zeichenkette();
                leer();
                erwarte(':');
                leer();
                m.put(k, wert());
                leer();
                if (pruefe('}')) return m;
                erwarte(',');
            }
        }

        private List<Object> liste() {
            List<Object> l = new ArrayList<>();
            i++;                       // '['
            leer();
            if (pruefe(']')) return l;
            while (true) {
                leer();
                l.add(wert());
                leer();
                if (pruefe(']')) return l;
                erwarte(',');
            }
        }

        private String zeichenkette() {
            erwarte('"');
            StringBuilder sb = new StringBuilder();
            while (true) {
                if (i >= s.length()) throw new IllegalArgumentException("Zeichenkette offen");
                char c = s.charAt(i++);
                if (c == '"') return sb.toString();
                if (c != '\\') { sb.append(c); continue; }
                char e = s.charAt(i++);
                switch (e) {
                    case '"'  -> sb.append('"');
                    case '\\' -> sb.append('\\');
                    case '/'  -> sb.append('/');
                    case 'b'  -> sb.append('\b');
                    case 'f'  -> sb.append('\f');
                    case 'n'  -> sb.append('\n');
                    case 'r'  -> sb.append('\r');
                    case 't'  -> sb.append('\t');
                    case 'u'  -> {
                        // Ersatzzeichenpaare (Emoji) ergeben sich automatisch,
                        // weil beide Haelften als char angehaengt werden.
                        sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                        i += 4;
                    }
                    default -> throw new IllegalArgumentException(
                            "Unbekannte Maskierung \\" + e);
                }
            }
        }

        private Object einfach() {
            if (s.startsWith("true", i))  { i += 4; return Boolean.TRUE; }
            if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
            if (s.startsWith("null", i))  { i += 4; return null; }
            int a = i;
            while (i < s.length() && "+-.eE0123456789".indexOf(s.charAt(i)) >= 0) i++;
            if (a == i) throw new IllegalArgumentException(
                    "Unerwartetes Zeichen '" + s.charAt(i) + "' an Position " + i);
            return Double.valueOf(s.substring(a, i));
        }

        private void leer() {
            while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++;
        }

        private boolean pruefe(char c) {
            if (i < s.length() && s.charAt(i) == c) { i++; return true; }
            return false;
        }

        private void erwarte(char c) {
            if (!pruefe(c)) throw new IllegalArgumentException(
                    "'" + c + "' erwartet an Position " + i);
        }
    }

    private static String kurz(String s) {
        if (s == null) return "(leer)";
        s = s.strip();
        return s.length() > 300 ? s.substring(0, 300) + " ..." : s;
    }

    // ─── Aufruf von der Kommandozeile ────────────────────────────────────────

    public static void main(String[] args) {
        try {
            String text;
            if (args.length >= 1) {
                text = Files.readString(Path.of(args[0]), StandardCharsets.UTF_8);
            } else if (System.in.available() > 0) {
                text = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
            } else {
                System.err.println("Aufruf:  java -jar jarvis-client.jar <textdatei> "
                        + "[\"eigener prompt\"]");
                System.err.println("   oder: cat datei.txt | java -jar jarvis-client.jar");
                System.err.println("   (mit JDK auch direkt: java JarvisClient.java <textdatei>)");
                System.err.println("Umgebung: JARVIS_URL und JARVIS_API_KEY sind optional – "
                        + "die Vorgaben stehen im Block S_URL/S_KEY im Quelltext.");
                System.exit(2);
                return;
            }
            if (text.isBlank()) {
                System.err.println("Der Text ist leer.");
                System.exit(2);
                return;
            }

            // Bewusst ueber den STATISCHEN Weg – derselbe, den ein Aufrufer als
            // Bibliothek benutzt. So wird hier genau das geprueft, was zaehlt.
            long t0 = System.nanoTime();
            String ergebnis = args.length >= 2
                    ? frage(text, args[1])
                    : frage(text);
            long ms = (System.nanoTime() - t0) / 1_000_000;

            System.out.println(ergebnis);
            System.err.printf("[%d Zeichen Eingabe | %d ms]%n", text.length(), ms);
        } catch (Exception e) {
            // Klartext statt Stapelspur: fuer ein Kommandozeilenwerkzeug ist die
            // Ursache die Information, nicht der Aufrufweg im JDK.
            System.err.println("Fehler: " + e.getMessage());
            System.exit(1);
        }
    }
}
