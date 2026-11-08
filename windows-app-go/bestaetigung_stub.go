//go:build !windows

package main

import "time"

// Ausserhalb von Windows gibt es keinen nativen Dialog: die App meldet dem
// Server dann KEINE Bestaetigungsfaehigkeit, und der Server weist wirksame
// Aktionen ab (fail-closed). Eine stille Zustimmung waere hier der Fehler.

// KannBestaetigen meldet, ob diese App Bestaetigungen anzeigen kann.
func KannBestaetigen() bool { return false }

// ZeigeBestaetigung lehnt ohne Dialog immer ab.
func ZeigeBestaetigung(titel, text string, frist time.Duration) bool { return false }
