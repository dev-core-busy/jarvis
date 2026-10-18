package hilfen

import "strings"

// PSZeichenkette setzt s als woertliche PowerShell-Zeichenkette in einfache
// Anfuehrungszeichen.
//
// Code-Review 2026-10-18: Temp-Pfade landeten ungeschuetzt zwischen '...' im
// Skript. Ein Benutzerprofil mit Apostroph (C:\Users\o'brien\AppData\...)
// beendete die Zeichenkette vorzeitig – das Skript brach ab oder fuehrte den
// Rest des Pfades als Befehl aus. In einfachen Anfuehrungszeichen ist das
// Verdoppeln die einzige noetige Maskierung; PowerShell wertet dabei auch die
// typografischen Apostrophe U+2018..U+201B als einfache Anfuehrungszeichen,
// deshalb werden sie ebenfalls verdoppelt.
func PSZeichenkette(s string) string {
	var b strings.Builder
	b.Grow(len(s) + 2)
	b.WriteByte('\'')
	for _, r := range s {
		switch r {
		case '\'', '\u2018', '\u2019', '\u201A', '\u201B':
			b.WriteRune(r)
		}
		b.WriteRune(r)
	}
	b.WriteByte('\'')
	return b.String()
}
