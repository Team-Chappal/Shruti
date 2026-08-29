plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "dev.shruti"
    compileSdk = 34

    defaultConfig {
        applicationId = "dev.shruti"
        minSdk = 28
        targetSdk = 34
        versionCode = 2
        versionName = "0.2.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
        debug {
            isDebuggable = true
        }
    }
    lint {
        // The :app module ships Compose UI; the Android Lint
        // baseline for Compose contains a few intentional
        // warnings (e.g. UnusedResources on preview composables
        // and MissingTranslation — we ship English-only). We
        // surface them but don't fail the build on them.
        // The :protocol module has its own lint config that
        // IS enforced.
        checkReleaseBuilds = true
        abortOnError = false
    }
    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    // Pin the Compose compiler explicitly to match Kotlin
    // 1.9.22. Without this pin, the Compose compiler is
    // selected by the Kotlin Gradle plugin based on the
    // Kotlin version, and that selection can drift from the
    // compose-runtime version pinned by the BOM below. The
    // 1.5.8 compiler is the version that ships with Kotlin
    // 1.9.22 and matches the runtime shape of compose-runtime
    // 1.5.4 in the BOM. Mismatch between the two is the
    // source of the "couldn't find inline method
    // CompositionLocal.getCurrent()" crash that has been
    // latent since the autonomous build (CI only runs
    // :protocol:test, never :app:assembleDebug).
    buildFeatures {
        compose = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.8"
    }
}

dependencies {
    implementation(project(":protocol"))
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.7.0")
    implementation("androidx.activity:activity-compose:1.8.0")
    implementation(platform("androidx.compose:compose-bom:2023.10.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.material3:material3")
    // WebSocket transport (T01). OkHttp is the smallest reliable
    // WS client that supports binary frames; the phone packs the
    // same wire format it always has, just over a WebSocket
    // envelope instead of a raw TCP socket.
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // T19 inbound WebSocket server (phone-as-server). The laptop
    // dials the phone directly when the Wi-Fi AP has client
    // isolation enabled (Android phone hotspots, which is the
    // common case in the field). Implemented in
    // [dev.shruti.transport.InboundWebSocketServer] using only
    // java.net.ServerSocket and the RFC 6455 handshake — a
    // previous attempt with org.java-websocket:Java-WebSocket
    // 1.6.0 bound the socket but the accept() loop silently
    // failed with EPERM on Android 16 (realme + Nothing A059),
    // so we dropped the dependency and wrote the accept loop
    // ourselves. No third-party deps on the inbound side.
    testImplementation("junit:junit:4.13.2")
    // OkHttp's MockWebServer spins up a real local HTTP server
    // in tests so we can assert byte-exact WS frame delivery
    // from TransportClient (T01 acceptance criterion).
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    // Robolectric runs the Android stubs (SharedPreferences,
    // Context.getSharedPreferences) under a JVM test runner.
    testImplementation("org.robolectric:robolectric:4.11.1")
    testImplementation("androidx.test:core:1.5.0")
    testImplementation("androidx.test.ext:junit:1.1.5")
}
