package com.ifinmail.update

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/**
 * Turns the server's manifest into an offer, and refuses anything this app should not act on.
 *
 * The manifest arrives over TLS from the operator's own server, so it is trusted for what is
 * *available*; it is still validated, because a bad or truncated document must never turn into an
 * install attempt. Whether a file may replace the installed app is decided separately, by
 * comparing signing certificates on the device.
 */
object UpdateManifest {
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = false
    }

    private val sha256Pattern = Regex("^[0-9a-fA-F]{64}$")

    /** Largest download this client will accept. APKs of this app are a few MB. */
    const val MAX_APK_BYTES: Long = 200L * 1024 * 1024

    /**
     * @param baseUrl the update server this device was configured with; relative download paths
     *   are resolved against it, so the link never depends on what host the server believes it has
     * @param expectedPackage the application id the build must carry (this app's own id)
     * @param allowInsecure permit `http://` download links (debug builds talking to a dev server)
     */
    fun parse(
        body: String,
        baseUrl: String,
        installedVersionCode: Int,
        expectedPackage: String,
        allowInsecure: Boolean = false
    ): CheckResult {
        val dto = try {
            json.decodeFromString(ManifestDto.serializer(), body)
        } catch (e: SerializationException) {
            throw UpdateException(UpdateFailure.BAD_RESPONSE, "The update server sent something unreadable.", e)
        } catch (e: IllegalArgumentException) {
            throw UpdateException(UpdateFailure.BAD_RESPONSE, "The update server sent something unreadable.", e)
        }
        val latest = dto.latest ?: return CheckResult.UpToDate(null)
        if (!dto.updateAvailable || latest.versionCode <= installedVersionCode) {
            return CheckResult.UpToDate(latest.versionName.ifBlank { null })
        }

        val url = if (latest.downloadPath.startsWith("/")) {
            baseUrl.trimEnd('/') + latest.downloadPath
        } else {
            latest.downloadUrl
        }
        val release = ReleaseInfo(
            versionCode = latest.versionCode,
            versionName = latest.versionName.ifBlank { latest.versionCode.toString() },
            notes = latest.notes.trim(),
            sizeBytes = latest.sizeBytes,
            sha256 = latest.sha256.lowercase(),
            signingCertSha256 = latest.signingCertSha256.lowercase(),
            minSdk = latest.minSdk,
            packageName = latest.`package`,
            downloadUrl = url,
            releasedAt = latest.releasedAt
        )
        validate(release, expectedPackage, allowInsecure)
        return CheckResult.Available(
            UpdateOffer(
                release = release,
                required = dto.mandatory,
                minimumVersionCode = dto.minimumVersionCode
            )
        )
    }

    private fun validate(release: ReleaseInfo, expectedPackage: String, allowInsecure: Boolean) {
        fun reject(message: String): Nothing = throw UpdateException(UpdateFailure.REJECTED, message)

        if (release.packageName != expectedPackage) {
            reject("The offered build is for ${release.packageName.ifBlank { "another app" }}, not this one.")
        }
        if (!sha256Pattern.matches(release.sha256)) {
            reject("The offered build has no usable checksum, so it was not downloaded.")
        }
        if (release.sizeBytes <= 0 || release.sizeBytes > MAX_APK_BYTES) {
            reject("The offered build reports an unusable size.")
        }
        val secure = release.downloadUrl.startsWith("https://", ignoreCase = true)
        val plain = release.downloadUrl.startsWith("http://", ignoreCase = true)
        if (!(secure || (allowInsecure && plain))) {
            reject("The offered build is not served over a secure connection, so it was not downloaded.")
        }
    }
}
