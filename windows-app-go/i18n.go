package main

// appLang ist die aktuelle UI-Sprache: "de" (Standard) oder "en".
// Wird beim Laden der Config gesetzt und beim Speichern der Einstellungen aktualisiert.
var appLang = "de"

// t gibt den deutschen oder englischen Text zurück – je nach appLang.
func t(de, en string) string {
	if appLang == "en" {
		return en
	}
	return de
}

// ── Wochentage / Monate für Datumstrenner ────────────────────────────────────

var weekdaysDE = []string{"Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"}
var weekdaysEN = []string{"Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"}

var monthsDE = []string{"", "Januar", "Februar", "März", "April", "Mai", "Juni",
	"Juli", "August", "September", "Oktober", "November", "Dezember"}
var monthsEN = []string{"", "January", "February", "March", "April", "May", "June",
	"July", "August", "September", "October", "November", "December"}

func weekdayName(idx int) string {
	if appLang == "en" {
		return weekdaysEN[idx]
	}
	return weekdaysDE[idx]
}

func monthName(idx int) string {
	if appLang == "en" {
		return monthsEN[idx]
	}
	return monthsDE[idx]
}
