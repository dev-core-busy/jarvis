package tlsvertrauen

// Waechter BSI M11 (Windows-App): die Regel und der echte TLS-Weg.
// Aufruf: cd windows-app-go && go test ./tlsvertrauen

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

type paar struct {
	cert *x509.Certificate
	key  *ecdsa.PrivateKey
}

func erzeuge(t *testing.T, name string, ips []net.IP, ca *paar) paar {
	t.Helper()
	k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tpl := &x509.Certificate{
		SerialNumber: big.NewInt(time.Now().UnixNano()),
		Subject:      pkix.Name{CommonName: name},
		NotBefore:    time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour),
		KeyUsage:    x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		IPAddresses: ips,
	}
	if name != "" && ips == nil {
		tpl.DNSNames = []string{name}
	}
	eltern, ekey := tpl, k
	if ca == nil {
		tpl.IsCA, tpl.BasicConstraintsValid = true, true
	} else {
		eltern, ekey = ca.cert, ca.key
	}
	der, err := x509.CreateCertificate(rand.Reader, tpl, eltern, &k.PublicKey, ekey)
	if err != nil {
		t.Fatal(err)
	}
	c, _ := x509.ParseCertificate(der)
	return paar{c, k}
}

func TestRegel(t *testing.T) {
	ca := erzeuge(t, "Firmen-CA", nil, nil)
	pool := x509.NewCertPool()
	pool.AddCert(ca.cert)
	SystemPool = pool
	defer func() { SystemPool = nil }()

	srv := erzeuge(t, "jarvis.firma.local", nil, &ca)
	if err := Pruefe("jarvis.firma.local", []*x509.Certificate{srv.cert, ca.cert}, ""); err != nil {
		t.Fatalf("CA-Kette mit passendem Namen muss gelten: %v", err)
	}
	if _, ok := AlsUnbekannt(Pruefe("anderer.firma.local", []*x509.Certificate{srv.cert}, "")); !ok {
		t.Fatal("falscher Name trotz gueltiger Kette muss abgewiesen werden")
	}
	ipz := erzeuge(t, "", []net.IP{net.ParseIP("192.0.2.7")}, &ca)
	if err := Pruefe("192.0.2.7", []*x509.Certificate{ipz.cert}, ""); err != nil {
		t.Fatalf("IP im Zertifikat muss gegen die IP gelten: %v", err)
	}
	if _, ok := AlsUnbekannt(Pruefe("192.0.2.8", []*x509.Certificate{ipz.cert}, "")); !ok {
		t.Fatal("andere IP muss abgewiesen werden")
	}

	selbst := erzeuge(t, "dev", []net.IP{net.ParseIP("192.0.2.9")}, nil)
	err := Pruefe("192.0.2.9", []*x509.Certificate{selbst.cert}, "")
	u, ok := AlsUnbekannt(err)
	if !ok {
		t.Fatalf("selbstsigniert ohne Pin muss UnbekanntesZertifikat sein, war %v", err)
	}
	if u.Fingerabdruck != Fingerabdruck(selbst.cert.Raw) || len(u.Fingerabdruck) != 95 || u.Vorher != "" {
		t.Fatalf("Fingerabdruck falsch: %+v", u)
	}
	if err := Pruefe("192.0.2.9", []*x509.Certificate{selbst.cert}, u.Fingerabdruck); err != nil {
		t.Fatalf("bestaetigtes Zertifikat muss gelten: %v", err)
	}
	anderes := erzeuge(t, "dev", []net.IP{net.ParseIP("192.0.2.9")}, nil)
	u2, ok := AlsUnbekannt(Pruefe("192.0.2.9", []*x509.Certificate{anderes.cert}, u.Fingerabdruck))
	if !ok || u2.Vorher != u.Fingerabdruck {
		t.Fatal("Zertifikatswechsel muss auffallen und den alten Fingerabdruck nennen")
	}
	if _, ok := AlsUnbekannt(Pruefe("x", nil, "")); ok {
		t.Fatal("ohne Zertifikat kein Bestaetigungsangebot")
	}
	if Pruefe("x", nil, "") == nil {
		t.Fatal("ohne Zertifikat muss abgewiesen werden")
	}
}

func TestHostAus(t *testing.T) {
	for ein, soll := range map[string]string{
		"wss://192.0.2.1/ws":              "192.0.2.1",
		"https://Jarvis.Firma.Local:8443/": "jarvis.firma.local",
		"https://[2001:db8::1]:443/x":      "2001:db8::1",
		"http://u:p@host.beispiel.de/a?b":  "host.beispiel.de",
		"host.beispiel.de":                 "host.beispiel.de",
	} {
		if ist := HostAus(ein); ist != soll {
			t.Errorf("HostAus(%q) = %q, soll %q", ein, ist, soll)
		}
	}
}

// Echter TLS-Weg: httptest-Server mit eigenem Zertifikat, per IP angesprochen.
func TestServerTLSEchterWeg(t *testing.T) {
	s := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("ok"))
	}))
	defer s.Close()
	SetzePins(nil)
	c := &http.Client{Transport: &http.Transport{TLSClientConfig: ServerTLS(s.URL)}}
	_, err := c.Get(s.URL)
	u, ok := AlsUnbekannt(err)
	if !ok {
		t.Fatalf("ohne Bestaetigung muss die Verbindung scheitern (UnbekanntesZertifikat), war %v", err)
	}
	SetzePins(map[string]string{u.Host: u.Fingerabdruck})
	c2 := &http.Client{Transport: &http.Transport{TLSClientConfig: ServerTLS(s.URL)}}
	r, err := c2.Get(s.URL)
	if err != nil || r.StatusCode != 200 {
		t.Fatalf("nach Bestaetigung muss die Verbindung gehen: %v", err)
	}
	r.Body.Close()
	// Pin gilt nur fuer DIESEN Rechner
	SetzePins(map[string]string{"192.0.2.99": u.Fingerabdruck})
	c3 := &http.Client{Transport: &http.Transport{TLSClientConfig: ServerTLS(s.URL)}}
	if _, err := c3.Get(s.URL); err == nil {
		t.Fatal("Pin eines anderen Rechners darf nicht gelten")
	}
}
