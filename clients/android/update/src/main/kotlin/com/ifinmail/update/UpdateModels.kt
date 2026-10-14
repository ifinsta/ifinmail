package com.ifinmail.update

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** One installable build as the server describes it. */
data class ReleaseInfo(
    val versionCode: Int,
    val versionName: String,
    val notes: String,
    val sizeBytes: Long,
    val sha256: String,
    /** SHA-256 of the signing certificate; empty when the server could not read it. */
    val signingCertSha256: String,
    val minSdk: Int,
    val packageName: String,
    val downloadUrl: String,
    val releasedAt: String?
)

/** What the server told this device: an offer, and whether taking it is optional. */
data class UpdateOffer(
    val release: ReleaseInfo,
    /** True when this device is below the mandatory floor and must update to keep working. */
    val required: Boolean,
    val minimumVersionCode: Int
)

sealed interface CheckResult {
    /** Nothing newer is offered to this device. [latest] is what the server calls current, if any. */
    data class UpToDate(val latestVersionName: String?) : CheckResult

    data class Available(val offer: UpdateOffer) : CheckResult
}

enum class UpdateFailure {
    /** No connection, timeout, DNS: worth trying again later. */
    NETWORK,

    /** The server answered, but not with something this app can use. */
    BAD_RESPONSE,

    /** The file that arrived is not the file the server described. */
    INTEGRITY,

    /** The offered build is not safe to install (wrong app, wrong key, not downloadable securely). */
    REJECTED,

    /** The device has no room for the download. */
    STORAGE,

    CANCELLED
}

class UpdateException(
    val failure: UpdateFailure,
    override val message: String,
    cause: Throwable? = null
) : Exception(message, cause)

/** Wire format of ``GET /updates/v1/android/latest.json``. Unknown fields are ignored. */
@Serializable
internal data class ManifestDto(
    val schema: Int = 1,
    @SerialName("update_available") val updateAvailable: Boolean = false,
    val mandatory: Boolean = false,
    @SerialName("minimum_version_code") val minimumVersionCode: Int = 0,
    val latest: LatestDto? = null
)

@Serializable
internal data class LatestDto(
    @SerialName("version_code") val versionCode: Int,
    @SerialName("version_name") val versionName: String = "",
    @SerialName("released_at") val releasedAt: String? = null,
    val notes: String = "",
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    val sha256: String = "",
    @SerialName("signing_cert_sha256") val signingCertSha256: String = "",
    @SerialName("min_sdk") val minSdk: Int = 0,
    val `package`: String = "",
    @SerialName("download_url") val downloadUrl: String = "",
    @SerialName("download_path") val downloadPath: String = ""
)
