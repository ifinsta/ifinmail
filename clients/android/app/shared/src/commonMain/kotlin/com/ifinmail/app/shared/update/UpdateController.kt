package com.ifinmail.app.shared.update

import kotlinx.coroutines.flow.StateFlow

/** What the UI needs to say about one build; the platform fills it from the update manifest. */
data class UiUpdateInfo(
    val versionName: String,
    val versionCode: Int,
    val notes: String,
    val sizeBytes: Long,
    /** This device is below the mandatory floor: it must update before it can be used. */
    val required: Boolean
)

/** The update flow as the person sees it, one state at a time. */
sealed interface UpdateUiState {
    /** Nothing has been checked yet. */
    data object Idle : UpdateUiState

    data object Checking : UpdateUiState

    data class UpToDate(val checkedAtEpochMs: Long) : UpdateUiState

    data class Available(val info: UiUpdateInfo) : UpdateUiState

    data class Downloading(val info: UiUpdateInfo, val percent: Int) : UpdateUiState

    /** Downloaded and verified; installing needs one more tap or permission. */
    data class ReadyToInstall(val info: UiUpdateInfo) : UpdateUiState

    /** Android has to be told once that this app may install apps. */
    data class NeedsInstallPermission(val info: UiUpdateInfo) : UpdateUiState

    data class Installing(val info: UiUpdateInfo) : UpdateUiState

    /**
     * @param info the build the failed attempt was about, so the screen can offer "try again"
     */
    data class Failed(val message: String, val info: UiUpdateInfo?) : UpdateUiState
}

/** The build this screen is about, when the state is about one. */
val UpdateUiState.info: UiUpdateInfo?
    get() = when (this) {
        is UpdateUiState.Available -> info
        is UpdateUiState.Downloading -> info
        is UpdateUiState.ReadyToInstall -> info
        is UpdateUiState.NeedsInstallPermission -> info
        is UpdateUiState.Installing -> info
        is UpdateUiState.Failed -> info
        else -> null
    }

/** True when the person has to act on this update now (a mandatory build is in play). */
val UpdateUiState.isRequired: Boolean get() = info?.required == true

/**
 * The self-update flow of an in-house build: ask the operator's server, download a verified file,
 * hand it to the system installer. The Android implementation lives in the app module.
 */
interface UpdateController {
    val state: StateFlow<UpdateUiState>

    /** Installed version, for the settings page. */
    val currentVersionName: String
    val currentVersionCode: Int

    /** Where updates come from (host name), for the settings page. */
    val serverLabel: String

    /** Whether update notices may be shown outside the app. */
    val notificationsAllowed: StateFlow<Boolean>

    /** Asks the server now (also what "Check for updates" does). */
    fun check()

    /** Downloads (if needed), verifies and installs the offered build. */
    fun downloadAndInstall()

    /** Opens the system screen where the person lets this app install updates. */
    fun openInstallPermissionSettings()

    fun requestNotificationPermission()
}
