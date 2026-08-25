plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "ca.kmeng.persianocr"
    compileSdk = 34

    defaultConfig {
        applicationId = "ca.kmeng.persianocr"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"

        // Visible in the app (Settings screen) so a rebuilt APK is never
        // mistaken for an older one already on the device — every CI build
        // is a different git commit, and this is how you tell which one is
        // actually running without digging through Play Store-style version
        // numbers that don't change between commits.
        buildConfigField(
            "String",
            "BUILD_ID",
            "\"${(System.getenv("GITHUB_SHA") ?: "local").take(7)}\""
        )
    }

    signingConfigs {
        getByName("debug") {
            // Checked into the repo deliberately — a *debug* keystore carries
            // no real trust and is meant to be shared across every machine
            // that builds this app, the opposite of a release key. Without
            // this, every CI run generates a fresh one (GitHub Actions
            // runners are ephemeral), so each new debug APK is signed
            // differently and Android refuses to install it over the
            // previous one — "App not installed" with no useful reason
            // shown, forcing an uninstall before every single update. One
            // fixed keystore means a new build always upgrades in place.
            storeFile = file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
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
        viewBinding = true
        buildConfig = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation("androidx.activity:activity-ktx:1.9.1")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
}
