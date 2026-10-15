plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.example.galaxywatch8"
    // compileSdk 35 = Android 15 – deckt Wear OS 5/6 (Galaxy Watch 8) ab
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.galaxywatch8"
        // minSdk 30 = Wear OS 3 (One UI Watch), Galaxy Watch 8 laeuft auf Wear OS 6
        minSdk = 30
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
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
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.play.services.wearable)

    // Jetpack Compose via Bill of Materials (BOM) – garantiert kompatible Versionen
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.tooling.preview)

    // Compose for Wear OS
    implementation(libs.wear.compose.material)
    implementation(libs.wear.compose.foundation)
    implementation(libs.wear.tooling.preview)

    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.core.splashscreen)

    // Nur fuer das @Preview-Rendering im Android Studio
    debugImplementation(libs.androidx.compose.ui.tooling)
}
