package com.ifinmail.update

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.ifinmail.BuildConfig
import com.ifinmail.app.shared.update.UiUpdateInfo
import com.ifinmail.app.shared.update.UpdateController
import com.ifinmail.app.shared.update.UpdateUiState
import com.ifinmail.app.shared.update.info
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.UUID

/**
 * The in-house update flow on Android.
 *
 * Order of events, and what stops each step from doing harm:
 * 1. ask the operator's server which build this device should run;
 * 2. download it into the app's private cache, resuming if interrupted, and refuse it unless size
 *    and SHA-256 match what the server announced;
 * 3. open the file with the platform and refuse it unless it is this app, the announced version, and
 *    signed with the same certificate as the installed app (Android would refuse too; checking first
 *    means the person is told why instead of seeing a generic installer error);
 * 4. hand it to the system installer, which asks the person to confirm.
 */
class AndroidUpdateController(
    context: Context,
    private val baseUrl: String = BuildConfig.UPDATE_BASE_URL,
    private val channel: String = BuildConfig.UPDATE_CHANNEL,
    private val allowInsecure: Boolean = BuildConfig.UPDATE_ALLOW_INSECURE
) : UpdateController {

    private val app: Context = context.applicationContext
    private val prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val downloads = com.ifinmail.update.UpdateDownloader(File(app.cacheDir, "updates"))
    private val checker = com.ifinmail.update.UpdateChecker(
        baseUrl = baseUrl,
        expectedPackage = app.packageName,
        allowInsecure = allowInsecure
    )

    private val _state = MutableStateFlow<UpdateUiState>(UpdateUiState.Idle)
    override val state: StateFlow<UpdateUiState> = _state.asStateFlow()

    private val _notificationsAllowed = MutableStateFlow(notificationsEnabled())
    override val notificationsAllowed: StateFlow<Boolean> = _notificationsAllowed.asStateFlow()

    private var offer: com.ifinmail.update.UpdateOffer? = null
    private var work: Job? = null

    /** Set by the activity so a permission request can be shown from here. */
    var notificationPermissionRequester: (() -> Unit)? = null

    private val installed: PackageInfo = app.packageManager.getPackageInfo(app.packageName, 0)

    override val currentVersionCode: Int =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) installed.longVersionCode.toInt()
        else @Suppress("DEPRECATION") installed.versionCode
    override val currentVersionName: String = installed.versionName.orEmpty()
    override val serverLabel: String = Uri.parse(baseUrl).host.orEmpty()

    /** False when this build was made without an update server. */
    val enabled: Boolean get() = baseUrl.isNotBlank()

    init {
        // First launch of a new build (an update just landed): the downloaded file has done its job
        // and the old answer says nothing about this version, so ask again at once.
        if (prefs.getInt(KEY_SEEN_VERSION, 0) != currentVersionCode) {
            prefs.edit().putInt(KEY_SEEN_VERSION, currentVersionCode).putLong(KEY_LAST_CHECK, 0L).apply()
            scope.launch { downloads.cleanup(keepVersionCode = null) }
        }
    }

    private val installId: String
        get() = prefs.getString(KEY_INSTALL_ID, null) ?: UUID.randomUUID().toString().also {
            prefs.edit().putString(KEY_INSTALL_ID, it).apply()
        }

    // -- checking ------------------------------------------------------------------------

    /** Asks again only if the last answer is old; what the app does when it comes to the front. */
    fun checkIfDue(maxAgeMs: Long = CHECK_EVERY_MS) {
        if (!enabled) return
        val last = prefs.getLong(KEY_LAST_CHECK, 0L)
        if (System.currentTimeMillis() - last >= maxAgeMs && _state.value.isIdleOrSettled()) check()
    }

    override fun check() {
        if (!enabled || work?.isActive == true) return
        refreshNotificationState()
        _state.value = UpdateUiState.Checking
        work = scope.launch {
            _state.value = try {
                evaluate()
            } catch (e: com.ifinmail.update.UpdateException) {
                UpdateUiState.Failed(e.message, info = null)
            }
        }
    }

    /**
     * One check without touching the screen state; the background worker uses this.
     * Returns the offer when there is a newer build for this device, or null.
     */
    fun peekOffer(): com.ifinmail.update.UpdateOffer? {
        if (!enabled) return null
        return when (val result = checker.check(deviceProfile())) {
            is com.ifinmail.update.CheckResult.Available -> result.offer
            is com.ifinmail.update.CheckResult.UpToDate -> null
        }.also { prefs.edit().putLong(KEY_LAST_CHECK, System.currentTimeMillis()).apply() }
    }

    private fun evaluate(): UpdateUiState {
        val result = checker.check(deviceProfile())
        val now = System.currentTimeMillis()
        prefs.edit().putLong(KEY_LAST_CHECK, now).apply()
        return when (result) {
            is com.ifinmail.update.CheckResult.UpToDate -> {
                offer = null
                downloads.cleanup(keepVersionCode = null)
                UpdateUiState.UpToDate(now)
            }
            is com.ifinmail.update.CheckResult.Available -> {
                offer = result.offer
                downloads.cleanup(keepVersionCode = result.offer.release.versionCode)
                val info = result.offer.toUi()
                if (downloads.existing(result.offer.release) != null) {
                    UpdateUiState.ReadyToInstall(info)
                } else {
                    UpdateUiState.Available(info)
                }
            }
        }
    }

    private fun deviceProfile() = com.ifinmail.update.DeviceProfile(
        versionCode = currentVersionCode,
        versionName = currentVersionName,
        sdkInt = Build.VERSION.SDK_INT,
        installId = installId,
        channel = channel
    )

    // -- downloading and installing --------------------------------------------------------

    override fun downloadAndInstall() {
        val current = offer ?: return check()
        if (work?.isActive == true) return
        val info = current.toUi()
        work = scope.launch {
            try {
                _state.value = UpdateUiState.Downloading(info, 0)
                val file = downloads.download(
                    current.release,
                    isCancelled = { !isActive },
                    onProgress = { done, total ->
                        val percent = if (total > 0) ((done * 100) / total).toInt().coerceIn(0, 100) else 0
                        _state.value = UpdateUiState.Downloading(info, percent)
                    }
                )
                verifyIdentity(file, current)
                installFromFile(file, info)
            } catch (e: com.ifinmail.update.UpdateException) {
                if (e.failure == com.ifinmail.update.UpdateFailure.CANCELLED) return@launch
                _state.value = UpdateUiState.Failed(userMessage(e), info)
            } catch (e: IOException) {
                _state.value = UpdateUiState.Failed("The update could not be prepared: ${e.message}", info)
            }
        }
    }

    /** Refuses a file that is not this app, not the announced version, or signed by another key. */
    private fun verifyIdentity(file: File, offer: com.ifinmail.update.UpdateOffer) {
        fun reject(message: String): Nothing {
            file.delete()
            throw com.ifinmail.update.UpdateException(com.ifinmail.update.UpdateFailure.REJECTED, message)
        }
        val archive = archiveInfo(file) ?: reject("The downloaded file is not an installable app.")
        if (archive.packageName != app.packageName) reject("The downloaded file is for a different app.")
        val archiveCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) archive.longVersionCode.toInt()
        else @Suppress("DEPRECATION") archive.versionCode
        if (archiveCode != offer.release.versionCode) reject("The downloaded file is not the version announced.")
        val theirs = signerDigests(archive)
        val ours = signerDigests(currentSignedInfo())
        if (theirs.isEmpty() || ours.isEmpty() || theirs.intersect(ours).isEmpty()) {
            reject("This update is signed with a different key than the installed app, so Android would refuse it.")
        }
    }

    @Suppress("DEPRECATION")
    private fun archiveInfo(file: File): PackageInfo? {
        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) PackageManager.GET_SIGNING_CERTIFICATES
        else PackageManager.GET_SIGNATURES
        return app.packageManager.getPackageArchiveInfo(file.absolutePath, flags)
    }

    @Suppress("DEPRECATION")
    private fun currentSignedInfo(): PackageInfo {
        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) PackageManager.GET_SIGNING_CERTIFICATES
        else PackageManager.GET_SIGNATURES
        return app.packageManager.getPackageInfo(app.packageName, flags)
    }

    @Suppress("DEPRECATION")
    private fun signerDigests(info: PackageInfo): Set<String> {
        val signatures = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            val signing = info.signingInfo ?: return emptySet()
            // Past keys count too: an app that rotated its key stays updatable from an older one.
            if (signing.hasMultipleSigners()) signing.apkContentsSigners.toList()
            else signing.signingCertificateHistory.toList()
        } else {
            info.signatures?.toList().orEmpty()
        }
        return signatures.map { sig ->
            MessageDigest.getInstance("SHA-256").digest(sig.toByteArray())
                .joinToString("") { "%02x".format(it) }
        }.toSet()
    }

    private fun installFromFile(file: File, info: UiUpdateInfo) {
        if (!app.packageManager.canRequestPackageInstalls()) {
            _state.value = UpdateUiState.NeedsInstallPermission(info)
            return
        }
        _state.value = UpdateUiState.Installing(info)
        val installer = app.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
            setAppPackageName(app.packageName)
            setSize(file.length())
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
            }
        }
        val sessionId = installer.createSession(params)
        installer.openSession(sessionId).use { session ->
            file.inputStream().use { input ->
                session.openWrite("ifinmail.apk", 0, file.length()).use { out ->
                    input.copyTo(out)
                    session.fsync(out)
                }
            }
            val callback = Intent(app, UpdateInstallReceiver::class.java).setAction(UpdateInstallReceiver.ACTION)
            val pending = PendingIntent.getBroadcast(
                app, sessionId, callback,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
            )
            session.commit(pending.intentSender)
        }
    }

    /** Called by [UpdateInstallReceiver] when the system installer answers. */
    internal fun onInstallResult(status: Int, message: String?) {
        if (status == PackageInstaller.STATUS_SUCCESS) return // the process is replaced; nothing to show
        val info = _state.value.info
        // Play Protect (and OEM scanners) ask about a build they have not seen. Declining their
        // prompt is reported as a verification failure; it is the person's choice, so the app only
        // says what happened and leaves "Try again" to them.
        val scanRefused = message?.contains("VERIFICATION", ignoreCase = true) == true
        _state.value = UpdateUiState.Failed(
            when {
                scanRefused ->
                    "Android's security check (Play Protect) did not allow the install. Try again and choose Install."
                status == PackageInstaller.STATUS_FAILURE_ABORTED -> "The installation was cancelled."
                status == PackageInstaller.STATUS_FAILURE_STORAGE ->
                    "There is not enough space to install the update."
                status == PackageInstaller.STATUS_FAILURE_CONFLICT ||
                    status == PackageInstaller.STATUS_FAILURE_INCOMPATIBLE ->
                    "Android refused the update: it does not match the installed app."
                else -> message?.takeIf { it.isNotBlank() } ?: "The installation did not complete."
            },
            info
        )
    }

    override fun openInstallPermissionSettings() {
        val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${app.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        app.startActivity(intent)
    }

    /** The person came back from the install-permission screen: continue if it was granted. */
    fun onResumed() {
        refreshNotificationState()
        val current = _state.value
        if (current is UpdateUiState.NeedsInstallPermission && app.packageManager.canRequestPackageInstalls()) {
            downloadAndInstall()
        }
    }

    // -- notifications ---------------------------------------------------------------------

    override fun requestNotificationPermission() {
        notificationPermissionRequester?.invoke()
    }

    fun refreshNotificationState() {
        _notificationsAllowed.value = notificationsEnabled()
    }

    private fun notificationsEnabled(): Boolean {
        val granted = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(app, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
        return granted && NotificationManagerCompat.from(app).areNotificationsEnabled()
    }

    // -- helpers ---------------------------------------------------------------------------

    private fun com.ifinmail.update.UpdateOffer.toUi() = UiUpdateInfo(
        versionName = release.versionName,
        versionCode = release.versionCode,
        notes = release.notes,
        sizeBytes = release.sizeBytes,
        required = required
    )

    private fun userMessage(e: com.ifinmail.update.UpdateException): String = when (e.failure) {
        com.ifinmail.update.UpdateFailure.NETWORK -> "The download was interrupted. Check the connection and try again."
        else -> e.message
    }

    private fun UpdateUiState.isIdleOrSettled(): Boolean = this is UpdateUiState.Idle ||
        this is UpdateUiState.UpToDate || this is UpdateUiState.Failed

    private companion object {
        const val PREFS = "ifinmail_updates"
        const val KEY_INSTALL_ID = "install_id"
        const val KEY_LAST_CHECK = "last_check_ms"
        const val KEY_SEEN_VERSION = "seen_version_code"

        /** A manifest is a few hundred bytes; an hour keeps a mandatory update from waiting long. */
        const val CHECK_EVERY_MS = 60L * 60 * 1000
    }
}
