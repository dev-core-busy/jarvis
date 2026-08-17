import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.hilt.android)
    alias(libs.plugins.ksp)
}

android {
    namespace = "info.jarvisai.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "info.jarvisai.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 857
        versionName = "0.857"

    }

    // Signatur-Zugangsdaten kommen aus android/keystore.properties (gitignored)
    // oder aus der Umgebung. NIE hier im Klartext: bis 2026-08-17 standen
    // Keystore UND Kennwort im OEFFENTLICHEN Repo - der Schluessel war damit
    // verbrannt und musste getauscht werden.
    val ksProps = Properties().apply {
        val f = rootProject.file("keystore.properties")
        if (f.exists()) f.inputStream().use { load(it) }
    }
    fun ks(name: String, env: String): String? =
        (ksProps.getProperty(name) ?: System.getenv(env))?.takeIf { it.isNotBlank() }

    val ksFile = ks("storeFile", "JARVIS_ANDROID_KEYSTORE") ?: "jarvis-release-neu.jks"
    val ksPass = ks("storePassword", "JARVIS_ANDROID_STOREPASS")
    val ksAlias = ks("keyAlias", "JARVIS_ANDROID_KEYALIAS") ?: "jarvis"
    val ksKeyPass = ks("keyPassword", "JARVIS_ANDROID_KEYPASS") ?: ksPass
    // Nur wenn Datei UND Kennwort vorhanden sind, gibt es eine Release-Signatur.
    // Fehlt etwas, bleibt der Build moeglich (debug-signiert) statt mit einem
    // Gradle-Fehler abzubrechen, den niemand deuten kann.
    val signierbar = ksPass != null && rootProject.file(ksFile).exists()

    signingConfigs {
        if (signierbar) {
            create("release") {
                storeFile = rootProject.file(ksFile)
                storePassword = ksPass
                keyAlias = ksAlias
                keyPassword = ksKeyPass
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (signierbar) {
                signingConfig = signingConfigs.getByName("release")
            } else {
                logger.warn("[jarvis] Keine Release-Signatur: android/keystore.properties " +
                        "fehlt oder ist unvollstaendig - das APK wird NICHT release-signiert.")
            }
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons.extended)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.security.crypto)
    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)
    implementation(libs.hilt.navigation.compose)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    debugImplementation(libs.androidx.ui.tooling)
}
