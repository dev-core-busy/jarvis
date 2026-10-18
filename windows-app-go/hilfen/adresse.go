// Paket hilfen buendelt kleine, plattformunabhaengige Helfer des Windows-Clients.
//
// Code-Review 2026-10-18: die Helfer liegen bewusst in einem eigenen Paket ohne
// Fyne/cgo-Abhaengigkeit – das Hauptpaket baut unter Linux nicht (Windows-only
// syscall-Felder), dieses Paket schon, und damit laufen seine Go-Tests auch auf
// dem Entwicklungsrechner (wie tlsvertrauen).
package hilfen

import "strings"

// HTTPBasis leitet aus der konfigurierten Server-Adresse (meist wss://host/ws)
// die HTTP-Basis fuer REST-Aufrufe ab, ohne abschliessendes "/ws" und ohne "/".
//
// Code-Review 2026-10-18: vorher gab es drei Fassungen (wsURLToHTTPS,
// issuesBaseURL, SetImageServer) mit verschiedenem Verhalten – zwei ersetzten
// "ws://" per ReplaceAll an beliebiger Stelle, eine verwarf den Pfad und
// erzwang https. Jetzt gilt EINE Regel:
//   - wss://, https:// und eine Adresse ohne Schema -> https://
//   - nur ein AUSDRUECKLICH unverschluesseltes ws:// bzw. http:// -> http://
//   - ein Pfad-Praefix (Reverse-Proxy, z.B. /jarvis/ws) bleibt erhalten,
//     nur das abschliessende "/ws" faellt weg.
func HTTPBasis(serverURL string) string {
	u := strings.TrimSpace(serverURL)
	schema := "https://"
	low := strings.ToLower(u)
	switch {
	case strings.HasPrefix(low, "wss://"):
		u = u[len("wss://"):]
	case strings.HasPrefix(low, "https://"):
		u = u[len("https://"):]
	case strings.HasPrefix(low, "ws://"):
		u = u[len("ws://"):]
		schema = "http://"
	case strings.HasPrefix(low, "http://"):
		u = u[len("http://"):]
		schema = "http://"
	}
	// Abfrage und Fragment gehoeren nicht zur Basis
	if i := strings.IndexAny(u, "?#"); i >= 0 {
		u = u[:i]
	}
	u = strings.TrimRight(u, "/")
	u = strings.TrimSuffix(u, "/ws")
	u = strings.TrimRight(u, "/")
	if u == "" {
		return ""
	}
	return schema + u
}
