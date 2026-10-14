buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        // The R8 bundled with AGP 9.0 predates Kotlin 2.4 and logs "error parsing kotlin metadata"
        // for every Kotlin class. AGP resolves R8 from the build classpath, so pinning a newer one
        // here fixes the warnings without changing AGP.
        classpath("com.android.tools:r8:9.5.26")
    }
}

plugins {
    // this is necessary to avoid the plugins to be loaded multiple times
    // in each subproject's classloader
    alias(libs.plugins.androidApplication) apply false
    alias(libs.plugins.androidMultiplatformLibrary) apply false
    alias(libs.plugins.composeMultiplatform) apply false
    alias(libs.plugins.composeCompiler) apply false
    alias(libs.plugins.kotlinJvm) apply false
    alias(libs.plugins.kotlinMultiplatform) apply false
    alias(libs.plugins.kotlinSerialization) apply false
    alias(libs.plugins.ktor) apply false
}