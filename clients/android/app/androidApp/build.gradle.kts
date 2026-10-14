import java.util.Properties
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

// Release identity and update source come from Gradle properties (or environment variables on CI),
// so a pipeline can raise the version for every build without editing source:
//   ./gradlew :app:androidApp:assembleRelease -Pifinmail.versionCode=12 -Pifinmail.versionName=1.4.0
fun buildProperty(name: String, environment: String, default: String): String =
    (findProperty(name) as String?)?.takeIf { it.isNotBlank() }
        ?: System.getenv(environment)?.takeIf { it.isNotBlank() }
        ?: default

// Release signing material never lives in the repository. Provide it in clients/android/keystore.properties
// (see keystore.properties.example) or through IFINMAIL_KEYSTORE_* environment variables on CI.
// Without either, `assembleRelease` still builds, but produces an unsigned APK.
val keystoreProperties = Properties().apply {
    val file = rootProject.file("keystore.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

fun signingValue(property: String, environment: String): String? =
    keystoreProperties.getProperty(property) ?: System.getenv(environment)

plugins {
    alias(libs.plugins.androidApplication)
    alias(libs.plugins.composeCompiler)
}

kotlin {
    compilerOptions {
        jvmTarget = JvmTarget.JVM_11
    }
}
dependencies {
    implementation(project(":app:shared"))
    implementation(project(":mail"))
    implementation(project(":update"))
    implementation(libs.androidx.work.runtimeKtx)

    implementation(libs.androidx.activity.compose)
    implementation(libs.kotlinx.coroutinesCore)
    implementation(libs.okio)

    implementation(libs.compose.uiToolingPreview)
    debugImplementation(libs.compose.uiTooling)

    androidTestImplementation(project(":app:shared"))
    androidTestImplementation(libs.androidx.testExt.junit)
    androidTestImplementation(libs.androidx.testRunner)
    androidTestImplementation(libs.compose.uiTestJUnit4)
    // Accessibility Test Framework checks (touch targets, labels, contrast) for the audit test.
    androidTestImplementation("androidx.compose.ui:ui-test-junit4-accessibility:1.11.2")
    debugImplementation(libs.compose.uiTestManifest)
}

android {
    namespace = "com.ifinmail"
    compileSdk = libs.versions.android.compileSdk.get().toInt()

    defaultConfig {
        applicationId = "com.ifinmail"
        minSdk = libs.versions.android.minSdk.get().toInt()
        targetSdk = libs.versions.android.targetSdk.get().toInt()
        // versionCode must rise with every build that is published: devices only accept upgrades.
        versionCode = buildProperty("ifinmail.versionCode", "IFINMAIL_VERSION_CODE", "1").toInt()
        versionName = buildProperty("ifinmail.versionName", "IFINMAIL_VERSION_NAME", "1.0")

        // Where this build asks for updates ("" turns the feature off) and on which channel.
        val updateUrl = buildProperty("ifinmail.updateBaseUrl", "IFINMAIL_UPDATE_URL", "")
        val updateChannel = buildProperty("ifinmail.updateChannel", "IFINMAIL_UPDATE_CHANNEL", "stable")
        buildConfigField("String", "UPDATE_BASE_URL", "\"$updateUrl\"")
        buildConfigField("String", "UPDATE_CHANNEL", "\"$updateChannel\"")
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
    signingConfigs {
        val storeFilePath = signingValue("storeFile", "IFINMAIL_KEYSTORE_FILE")
        if (storeFilePath != null) {
            create("release") {
                storeFile = rootProject.file(storeFilePath)
                storePassword = signingValue("storePassword", "IFINMAIL_KEYSTORE_PASSWORD")
                keyAlias = signingValue("keyAlias", "IFINMAIL_KEY_ALIAS")
                keyPassword = signingValue("keyPassword", "IFINMAIL_KEY_PASSWORD")
            }
        }
    }
    buildTypes {
        debug {
            // A development server on the host machine (http://10.0.2.2:8000) is allowed to be
            // reached over plain HTTP; release builds only ever accept https.
            buildConfigField("boolean", "UPDATE_ALLOW_INSECURE", "true")
        }
        release {
            buildConfigField("boolean", "UPDATE_ALLOW_INSECURE", "false")
            signingConfig = signingConfigs.findByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}