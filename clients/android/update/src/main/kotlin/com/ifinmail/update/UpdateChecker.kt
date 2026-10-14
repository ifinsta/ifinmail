package com.ifinmail.update

import java.io.IOException
import java.net.URLEncoder

/** Who is asking, so the server can pick the right build and count adoption. */
data class DeviceProfile(
    val versionCode: Int,
    val versionName: String,
    val sdkInt: Int,
    /** A random identifier the app made for itself. Never an Android ID, account or address. */
    val installId: String,
    val channel: String = "stable"
)

/**
 * Asks the update server what this device should do.
 *
 * @param baseUrl the server's origin, e.g. `https://mail.example.org`
 * @param expectedPackage this app's application id; a build for anything else is refused
 */
class UpdateChecker(
    baseUrl: String,
    private val expectedPackage: String,
    private val http: UpdateHttp = JavaUpdateHttp(),
    private val allowInsecure: Boolean = false
) {
    private val baseUrl = baseUrl.trim().trimEnd('/')

    fun check(device: DeviceProfile): CheckResult {
        val url = manifestUrl(device)
        val body = try {
            http.open(url).use { response ->
                if (response.status != 200) {
                    throw UpdateException(
                        UpdateFailure.BAD_RESPONSE,
                        "The update server answered ${response.status}."
                    )
                }
                // The manifest is small; cap what is read so a bad server cannot fill memory.
                readBounded(response.body, MAX_MANIFEST_BYTES).toString(Charsets.UTF_8)
            }
        } catch (e: UpdateException) {
            throw e
        } catch (e: IOException) {
            throw UpdateException(UpdateFailure.NETWORK, "Could not reach the update server.", e)
        }
        return UpdateManifest.parse(
            body = body,
            baseUrl = baseUrl,
            installedVersionCode = device.versionCode,
            expectedPackage = expectedPackage,
            allowInsecure = allowInsecure
        )
    }

    internal fun manifestUrl(device: DeviceProfile): String {
        fun q(value: String) = URLEncoder.encode(value, "UTF-8")
        return "$baseUrl/updates/v1/android/latest.json" +
            "?channel=${q(device.channel)}" +
            "&version_code=${device.versionCode}" +
            "&version_name=${q(device.versionName)}" +
            "&sdk=${device.sdkInt}" +
            "&device=${q(device.installId)}"
    }

    // InputStream.readNBytes needs API 33; this app supports API 24.
    private fun readBounded(input: java.io.InputStream, limit: Int): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(4096)
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            out.write(buffer, 0, read)
            if (out.size() > limit) {
                throw UpdateException(UpdateFailure.BAD_RESPONSE, "The update answer was too large.")
            }
        }
        return out.toByteArray()
    }

    private companion object {
        const val MAX_MANIFEST_BYTES = 64 * 1024
    }
}
