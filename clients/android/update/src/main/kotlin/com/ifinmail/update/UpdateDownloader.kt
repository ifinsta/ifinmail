package com.ifinmail.update

import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.security.MessageDigest

/**
 * Downloads the offered build into [directory], verified.
 *
 * * Resumable: bytes already on disk are kept in a `.part` file and the transfer continues from
 *   there when the server honours `Range`; if it does not, the file starts over.
 * * Verified: the finished file must match the announced size and SHA-256 before it gets its
 *   final name. A mismatch deletes it. Nothing unverified is ever left under the final name.
 * * Cancellable: [isCancelled] is polled while streaming.
 */
class UpdateDownloader(
    private val directory: File,
    private val http: UpdateHttp = JavaUpdateHttp()
) {

    fun finalFile(release: ReleaseInfo): File = File(directory, "ifinmail-${release.versionCode}.apk")

    private fun partFile(release: ReleaseInfo): File = File(directory, "ifinmail-${release.versionCode}.apk.part")

    /** A previously verified download of exactly this build, or null. */
    fun existing(release: ReleaseInfo): File? {
        val file = finalFile(release)
        return file.takeIf { it.isFile && it.length() == release.sizeBytes && sha256(it) == release.sha256 }
    }

    /** Removes downloads of other versions and abandoned partial files. */
    fun cleanup(keepVersionCode: Int? = null) {
        directory.listFiles()?.forEach { file ->
            val keep = keepVersionCode != null && file.name.startsWith("ifinmail-$keepVersionCode.apk")
            if (!keep && file.name.startsWith("ifinmail-") && file.name.contains(".apk")) file.delete()
        }
    }

    fun download(
        release: ReleaseInfo,
        isCancelled: () -> Boolean = { false },
        onProgress: (downloaded: Long, total: Long) -> Unit = { _, _ -> }
    ): File {
        existing(release)?.let {
            onProgress(release.sizeBytes, release.sizeBytes)
            return it
        }
        if (!directory.isDirectory && !directory.mkdirs()) {
            throw UpdateException(UpdateFailure.STORAGE, "Could not create the download folder.")
        }
        val usable = directory.usableSpace
        if (usable in 0 until release.sizeBytes + SPACE_MARGIN) {
            throw UpdateException(UpdateFailure.STORAGE, "There is not enough free space for the update.")
        }
        val part = partFile(release)
        var have = if (part.isFile) part.length() else 0L
        if (have > release.sizeBytes) {
            part.delete()
            have = 0
        }
        try {
            if (have < release.sizeBytes) transfer(release, part, have, isCancelled, onProgress)
        } catch (e: UpdateException) {
            throw e
        } catch (e: IOException) {
            // The partial file is kept: the next attempt resumes from it.
            throw UpdateException(UpdateFailure.NETWORK, "The download was interrupted.", e)
        }

        if (part.length() != release.sizeBytes) {
            part.delete()
            throw UpdateException(UpdateFailure.INTEGRITY, "The downloaded file is not the size announced.")
        }
        if (sha256(part) != release.sha256) {
            part.delete()
            throw UpdateException(
                UpdateFailure.INTEGRITY,
                "The downloaded file does not match its checksum, so it was discarded."
            )
        }
        val target = finalFile(release)
        target.delete()
        if (!part.renameTo(target)) {
            throw UpdateException(UpdateFailure.STORAGE, "Could not store the downloaded update.")
        }
        return target
    }

    private fun transfer(
        release: ReleaseInfo,
        part: File,
        startAt: Long,
        isCancelled: () -> Boolean,
        onProgress: (Long, Long) -> Unit
    ) {
        http.open(release.downloadUrl, rangeStart = startAt).use { response ->
            var offset = startAt
            when {
                response.status == 206 && response.rangeStart == startAt -> Unit // resuming
                response.status == 200 -> offset = 0L // whole file (no range support, or first try)
                response.status == 416 -> {
                    part.delete()
                    throw UpdateException(UpdateFailure.NETWORK, "The download has to start over; try again.")
                }
                else -> throw UpdateException(
                    UpdateFailure.BAD_RESPONSE,
                    "The update file could not be fetched (HTTP ${response.status})."
                )
            }
            RandomAccessFile(part, "rw").use { out ->
                out.setLength(offset)
                out.seek(offset)
                val buffer = ByteArray(BUFFER)
                var written = offset
                var lastReport = 0L
                while (true) {
                    if (isCancelled()) throw UpdateException(UpdateFailure.CANCELLED, "The download was cancelled.")
                    val read = response.body.read(buffer)
                    if (read < 0) break
                    out.write(buffer, 0, read)
                    written += read
                    if (written > release.sizeBytes) {
                        out.setLength(0)
                        part.delete()
                        throw UpdateException(UpdateFailure.INTEGRITY, "The server sent more than it announced.")
                    }
                    if (written - lastReport >= REPORT_EVERY || written == release.sizeBytes) {
                        lastReport = written
                        onProgress(written, release.sizeBytes)
                    }
                }
                onProgress(written, release.sizeBytes)
                if (written < release.sizeBytes) {
                    // A dropped connection can look like a clean end of stream. Keep what arrived
                    // so the next attempt resumes instead of starting over.
                    throw UpdateException(UpdateFailure.NETWORK, "The download was interrupted.")
                }
            }
        }
    }

    companion object {
        private const val BUFFER = 64 * 1024
        private const val REPORT_EVERY = 128 * 1024L
        private const val SPACE_MARGIN = 8L * 1024 * 1024

        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(BUFFER)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    digest.update(buffer, 0, read)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }
    }
}
