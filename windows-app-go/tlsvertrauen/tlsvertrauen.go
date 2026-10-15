package tlsvertrauen

// Pruefung des Serverzertifikats (BSI M11, 2026-10-12).
//
// Bis hierher lief jede Verbindung der App mit InsecureSkipVerify – wer im Netz
// dazwischen sass, bekam Anmeldedaten und Sitzungstoken. Jetzt gilt:
//
//  1. Das Zertifikat wird normal geprueft (Vertrauensspeicher von Windows,
//     also auch die Firmen-CA, und der Servername bzw. die IP).
//  2. Scheitert das (Server per IP mit eigenem Zertifikat, selbst ausgestellt),
//     zaehlt nur noch ein ausdruecklich BESTAETIGTES Zertifikat: der Benutzer
//     sieht beim Anmelden den Fingerabdruck und bestaetigt ihn; gespeichert wird
//     er je Servername (Config.ServerCertPins). Ein anderes Zertifikat am selben
//     Namen faellt dann auf und braucht eine neue Bestaetigung.
//
// InsecureSkipVerify bleibt technisch gesetzt, weil die eigentliche Pruefung in
// VerifyConnection steckt (dort sind beide Wege moeglich); VerifyConnection laeuft
// in crypto/tls auch mit InsecureSkipVerify.

import (
	"crypto/sha256"
	"crypto/subtle"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"net"
	"strings"
	"sync"
)

// UnbekanntesZertifikat: weder vertrauenswuerdig noch bestaetigt.
type UnbekanntesZertifikat struct {
	Host          string
	Fingerabdruck string
	Vorher        string // bisher bestaetigter Fingerabdruck (Wechsel!) oder ""
	Grund         error
}

func (e *UnbekanntesZertifikat) Error() string {
	if e.Vorher != "" {
		return fmt.Sprintf("Das Zertifikat von %s hat sich geändert (neu %s)", e.Host, e.Fingerabdruck)
	}
	return fmt.Sprintf("Zertifikat von %s nicht bestätigt (%s)", e.Host, e.Fingerabdruck)
}

var (
	pinMu      sync.RWMutex
	pinMap     = map[string]string{}
	SystemPool *x509.CertPool // nil = Systemspeicher; nur Tests setzen ihn
)

// SetzePins uebernimmt die bestaetigten Fingerabdruecke (aus der Config).
func SetzePins(m map[string]string) {
	pinMu.Lock()
	defer pinMu.Unlock()
	pinMap = map[string]string{}
	for k, v := range m {
		pinMap[NormHost(k)] = v
	}
}

func PinFuer(host string) string {
	pinMu.RLock()
	defer pinMu.RUnlock()
	return pinMap[NormHost(host)]
}

// NormHost: Rechnername klein, ohne Port und Klammern.
func NormHost(h string) string {
	h = strings.ToLower(strings.TrimSpace(h))
	if hh, _, err := net.SplitHostPort(h); err == nil {
		h = hh
	}
	return strings.Trim(h, "[]")
}

// Fingerabdruck: SHA-256 des ganzen Zertifikats, AA:BB:… (wie Browser/openssl).
func Fingerabdruck(der []byte) string {
	s := sha256.Sum256(der)
	teile := make([]string, len(s))
	for i, b := range s {
		teile[i] = fmt.Sprintf("%02X", b)
	}
	return strings.Join(teile, ":")
}

// Pruefe ist die eigentliche Regel (ohne Netz, testbar).
func Pruefe(host string, certs []*x509.Certificate, pin string) error {
	if len(certs) == 0 {
		return errors.New("Server hat kein Zertifikat vorgelegt")
	}
	zwischen := x509.NewCertPool()
	for _, c := range certs[1:] {
		zwischen.AddCert(c)
	}
	_, err := certs[0].Verify(x509.VerifyOptions{
		DNSName: NormHost(host), Intermediates: zwischen, Roots: SystemPool,
	})
	if err == nil {
		return nil
	}
	fp := Fingerabdruck(certs[0].Raw)
	if pin != "" && subtle.ConstantTimeCompare([]byte(pin), []byte(fp)) == 1 {
		return nil
	}
	return &UnbekanntesZertifikat{Host: NormHost(host), Fingerabdruck: fp, Vorher: pin, Grund: err}
}

// HostAus: Rechnername bzw. IP aus einer Server-Adresse (https/wss/http/ws).
func HostAus(adresse string) string {
	a := strings.TrimSpace(adresse)
	if i := strings.Index(a, "://"); i >= 0 {
		a = a[i+3:]
	}
	if i := strings.IndexAny(a, "/?#"); i >= 0 {
		a = a[:i]
	}
	if i := strings.LastIndex(a, "@"); i >= 0 {
		a = a[i+1:]
	}
	return NormHost(a)
}

// ServerTLS: TLS-Konfiguration fuer ALLE Verbindungen zum Jarvis-Server.
//
// Der Rechnername kommt aus der ADRESSE, nicht aus ConnectionState.ServerName:
// bei einer IP laesst crypto/tls ServerName leer (gemessen 2026-10-12 gegen
// DEV) – die Namenspruefung liefe dann ins Leere, und der Pin waere keinem
// Server zugeordnet.
func ServerTLS(adresse string) *tls.Config {
	host := HostAus(adresse)
	return &tls.Config{
		InsecureSkipVerify: true, //nolint:gosec // geprueft in VerifyConnection
		MinVersion:         tls.VersionTLS12,
		VerifyConnection: func(cs tls.ConnectionState) error {
			return Pruefe(host, cs.PeerCertificates, PinFuer(host))
		},
	}
}

// AlsUnbekannt: steckt in err ein unbestaetigtes Zertifikat?
func AlsUnbekannt(err error) (*UnbekanntesZertifikat, bool) {
	var u *UnbekanntesZertifikat
	if errors.As(err, &u) {
		return u, true
	}
	return nil, false
}
