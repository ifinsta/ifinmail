import org.jetbrains.kotlin.gradle.dsl.JvmTarget

// Device-side update logic (manifest, version policy, resumable verified download). Plain JVM so it
// is tested against a real local HTTP server; the Android glue (PackageInstaller, notifications,
// scheduling) lives in :app:androidApp.
plugins {
    alias(libs.plugins.kotlinJvm)
    alias(libs.plugins.kotlinSerialization)
}

java {
    sourceCompatibility = JavaVersion.VERSION_11
    targetCompatibility = JavaVersion.VERSION_11
}

kotlin {
    compilerOptions {
        jvmTarget = JvmTarget.JVM_11
    }
}

dependencies {
    api(libs.kotlinx.coroutinesCore)
    implementation(libs.kotlinx.serializationJson)

    testImplementation(libs.kotlin.testJunit)
    testImplementation(libs.kotlinx.coroutinesTest)
}
