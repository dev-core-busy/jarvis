// Root-Build-Skript – definiert die Plugins fuer alle Module (apply false = nur Versionsdeklaration)
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
}
