This is a Kotlin Multiplatform project targeting Android, iOS, Web, Desktop (JVM), Server.

* [/app/iosApp](./app/iosApp/iosApp) contains an iOS application. Even if you’re sharing your UI with Compose Multiplatform,
  you need this entry point for your iOS app. This is also where you should add SwiftUI code for your project.

* [/app/shared](./app/shared/src) is for code that will be shared across your Compose Multiplatform applications.
  It contains several subfolders:
  - [commonMain](./app/shared/src/commonMain/kotlin) is for code that’s common for all targets.
  - Other folders are for Kotlin code that will be compiled for only the platform indicated in the folder name.
    For example, if you want to use Apple’s CoreCrypto for the iOS part of your Kotlin app,
    the [iosMain](./app/shared/src/iosMain/kotlin) folder would be the right place for such calls.
    Similarly, if you want to edit the Desktop (JVM) specific part, the [jvmMain](./app/shared/src/jvmMain/kotlin)
    folder is the appropriate location.

* [/core](./core/src) is for the code that will be shared between all targets in the project.
  The most important subfolder is [commonMain](./core/src/commonMain/kotlin). If preferred, you
  can add code to the platform-specific folders here too.

* [/server](./server/src/main/kotlin) is for the Ktor server application.

### Running the apps

Use the run configurations provided by the run widget in your IDE's toolbar. You can also use these commands and options:

- Android app: `./gradlew :app:androidApp:assembleDebug`
- Desktop app:
  - Hot reload: `./gradlew :app:desktopApp:hotRun --auto`
  - Standard run: `./gradlew :app:desktopApp:run`
- Server: `./gradlew :server:run`
- Web app:
  - Wasm target (faster, modern browsers): `./gradlew :app:webApp:wasmJsBrowserDevelopmentRun`
  - JS target (slower, supports older browsers): `./gradlew :app:webApp:jsBrowserDevelopmentRun`
- iOS app: open the [/app/iosApp](./app/iosApp) directory in Xcode and run it from there.

### Running tests

Use the run button in your IDE's editor gutter, or run tests using Gradle tasks:

- Android tests: `./gradlew :app:shared:testAndroidHostTest`
- Desktop tests: `./gradlew :app:shared:jvmTest`
- Server tests: `./gradlew :server:test`
- Web tests:
  - Wasm target: `./gradlew :app:shared:wasmJsTest`
  - JS target: `./gradlew :app:shared:jsTest`
- iOS tests: `./gradlew :app:shared:iosSimulatorArm64Test`

---

Learn more about [Kotlin Multiplatform](https://www.jetbrains.com/help/kotlin-multiplatform-dev/get-started.html),
[Compose Multiplatform](https://github.com/JetBrains/compose-multiplatform/#compose-multiplatform),
[Kotlin/Wasm](https://kotl.in/wasm/)…

We would appreciate your feedback on Compose/Web and Kotlin/Wasm in the public Slack channel [#compose-web](https://slack-chats.kotlinlang.org/c/compose-web).
If you face any issues, please report them on [YouTrack](https://youtrack.jetbrains.com/newIssue?project=CMP).

### Release builds and signing

`assembleRelease` minifies with R8 and shrinks resources. Signing material is never stored in the repository:

1. Create a key once and back it up (losing it means you cannot ship updates):
   `keytool -genkeypair -v -keystore ifinmail-release.jks -alias ifinmail -keyalg RSA -keysize 4096 -validity 10000`
2. Copy `keystore.properties.example` to `keystore.properties` (git-ignored) and fill it in, or set
   `IFINMAIL_KEYSTORE_FILE`, `IFINMAIL_KEYSTORE_PASSWORD`, `IFINMAIL_KEY_ALIAS`, `IFINMAIL_KEY_PASSWORD` on CI.
3. `./gradlew :app:androidApp:assembleRelease`

Without either, the build succeeds but produces an unsigned APK that cannot be installed.

### Updates (OTA)

The app updates itself from your own ifinmail server; no app store is involved. The `:update` module holds the
protocol (manifest, resumable SHA-256-verified download) and `androidApp/.../update/` hands the file to
`PackageInstaller`. Build-time settings (Gradle properties or `-P` flags):

| Property | Default | Meaning |
| --- | --- | --- |
| `ifinmail.versionCode` | `1` | Whole number, must increase with every release |
| `ifinmail.versionName` | `1.0` | Shown to people |
| `ifinmail.updateBaseUrl` | `https://mail.ifinsta.online` | Server that hosts the manifest and APKs |
| `ifinmail.updateChannel` | `stable` | `stable` or `beta` |

Version, sign, build, verify and publish with `python scripts/release.py` (or the *Android release* GitHub
workflow); the full workflow (channels, staged rollout, mandatory updates,
rollback, Play Protect) is in [`docs/android-releases.md`](../../docs/android-releases.md). Debug builds may
use cleartext to the emulator host (`10.0.2.2`) for local testing; release builds require https.

### Translations

All user-visible strings live in `app/shared/src/commonMain/composeResources/values/strings.xml`.
To add a language, create `values-<locale>/strings.xml` next to it (see `values-fr`). `StringCatalogueTest`
checks that every translation defines the same keys and format placeholders as the base catalogue.

### Quality checks

- `./gradlew :app:shared:jvmTest` — theme contrast (WCAG AA) and string-catalogue tests.
- `./gradlew :app:androidApp:connectedDebugAndroidTest` — UI tests plus an Accessibility Test Framework audit
  of every primary screen (set `ANDROID_SERIAL` when more than one device is attached).
