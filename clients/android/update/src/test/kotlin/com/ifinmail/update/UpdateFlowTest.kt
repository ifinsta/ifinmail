package com.ifinmail.update

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.io.File
import java.net.InetSocketAddress
import java.nio.file.Files
import java.security.MessageDigest
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** Everything runs over real sockets against a server written to misbehave on demand. */
class UpdateFlowTest {

    private lateinit var server: HttpServer
    private lateinit var dir: File
    private lateinit var base: String

    private val apk: ByteArray = ByteArray(700_000) { (it * 31 % 251).toByte() }
    private val apkSha: String = MessageDigest.getInstance("SHA-256").digest(apk)
        .joinToString("") { "%02x".format(it) }

    // knobs the handlers read
    @Volatile private var manifest: String = ""
    @Volatile private var honourRange = true
    @Volatile private var cutAfter: Int = -1 // close the connection after this many body bytes
    @Volatile private var served: ByteArray = apk
    @Volatile private var apkStatus = 200
    private val rangeRequests = mutableListOf<String?>()

    @BeforeTest
    fun start() {
        dir = Files.createTempDirectory("ifinmail-update-test").toFile()
        server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/updates/v1/android/latest.json") { ex ->
            val bytes = manifest.toByteArray()
            ex.sendResponseHeaders(200, bytes.size.toLong())
            ex.responseBody.use { it.write(bytes) }
        }
        server.createContext("/media/app.apk") { ex -> serveApk(ex) }
        server.start()
        base = "http://127.0.0.1:${server.address.port}"
        manifest = manifestJson(versionCode = 5)
    }

    @AfterTest
    fun stop() {
        server.stop(0)
        dir.deleteRecursively()
    }

    private fun serveApk(ex: HttpExchange) {
        val range = ex.requestHeaders.getFirst("Range")
        rangeRequests += range
        if (apkStatus != 200) {
            ex.sendResponseHeaders(apkStatus, -1)
            ex.close()
            return
        }
        var from = 0
        val body = served
        if (range != null && honourRange) {
            from = Regex("""bytes=(\d+)-""").find(range)!!.groupValues[1].toInt()
            ex.responseHeaders.add("Content-Range", "bytes $from-${body.size - 1}/${body.size}")
            ex.sendResponseHeaders(206, (body.size - from).toLong())
        } else {
            ex.sendResponseHeaders(200, body.size.toLong())
        }
        ex.responseBody.use { out ->
            val end = if (cutAfter >= 0) minOf(body.size, from + cutAfter) else body.size
            out.write(body, from, end - from)
            if (cutAfter >= 0) {
                out.flush()
                ex.close() // short of Content-Length: the client sees a truncated transfer
            }
        }
    }

    private fun manifestJson(
        versionCode: Int,
        mandatory: Boolean = false,
        available: Boolean = true,
        pkg: String = "com.ifinmail",
        sha: String = apkSha,
        size: Long = apk.size.toLong(),
        path: String = "/media/app.apk",
        url: String = ""
    ) = """
        {"schema":1,"update_available":$available,"mandatory":$mandatory,"minimum_version_code":3,
         "future_field":{"ignored":true},
         "latest":{"version_code":$versionCode,"version_name":"1.$versionCode.0","notes":" Faster sync ",
         "size_bytes":$size,"sha256":"$sha","signing_cert_sha256":"AB12","min_sdk":24,
         "package":"$pkg","download_path":"$path","download_url":"$url","released_at":"2026-10-14T08:00:00Z"}}
    """.trimIndent()

    private val device get() = DeviceProfile(versionCode = 2, versionName = "1.0", sdkInt = 34, installId = "install-1234abcd")
    private fun checker() = UpdateChecker(base, "com.ifinmail", allowInsecure = true)
    private fun offer(): UpdateOffer =
        (checker().check(device) as CheckResult.Available).offer

    // -- checking --------------------------------------------------------------------------

    @Test
    fun anOlderDeviceIsOfferedTheBuildWithEverythingItMustVerify() {
        val offer = offer()
        assertEquals(5, offer.release.versionCode)
        assertEquals("1.5.0", offer.release.versionName)
        assertEquals("Faster sync", offer.release.notes)
        assertEquals(apkSha, offer.release.sha256)
        assertEquals("ab12", offer.release.signingCertSha256)
        assertEquals("$base/media/app.apk", offer.release.downloadUrl)
        assertFalse(offer.required)
    }

    @Test
    fun theManifestRequestCarriesTheDeviceProfile() {
        val url = checker().manifestUrl(device)
        assertTrue(url.startsWith("$base/updates/v1/android/latest.json?"))
        for (part in listOf("channel=stable", "version_code=2", "sdk=34", "device=install-1234abcd")) {
            assertTrue(part in url, "missing $part in $url")
        }
    }

    @Test
    fun aMandatoryFlagMakesTheOfferRequired() {
        manifest = manifestJson(versionCode = 6, mandatory = true)
        val offer = offer()
        assertTrue(offer.required)
        assertEquals(3, offer.minimumVersionCode)
    }

    @Test
    fun noNewerBuildMeansUpToDate() {
        manifest = manifestJson(versionCode = 2, available = false)
        assertTrue(checker().check(device) is CheckResult.UpToDate)
        manifest = """{"schema":1,"update_available":false,"mandatory":false,"minimum_version_code":0,"latest":null}"""
        assertTrue(checker().check(device) is CheckResult.UpToDate)
    }

    @Test
    fun aBuildNoNewerThanTheInstalledOneIsNotOffered() {
        manifest = manifestJson(versionCode = 2, available = true)
        assertTrue(checker().check(device) is CheckResult.UpToDate)
    }

    @Test
    fun hostileOrBrokenManifestsAreRefused() {
        fun refused(body: String, failure: UpdateFailure) {
            manifest = body
            val e = assertFailsWith<UpdateException> { checker().check(device) }
            assertEquals(failure, e.failure, body.take(60))
        }
        refused("not json at all", UpdateFailure.BAD_RESPONSE)
        refused("{\"schema\":", UpdateFailure.BAD_RESPONSE)
        refused(manifestJson(5, pkg = "com.evil.app"), UpdateFailure.REJECTED)
        refused(manifestJson(5, sha = "abc"), UpdateFailure.REJECTED)
        refused(manifestJson(5, size = 0), UpdateFailure.REJECTED)
        refused(manifestJson(5, size = Long.MAX_VALUE), UpdateFailure.REJECTED)
        refused(manifestJson(5, path = "", url = "ftp://example.org/a.apk"), UpdateFailure.REJECTED)
    }

    @Test
    fun plainHttpIsRefusedUnlessTheBuildAllowsIt() {
        val strict = UpdateChecker(base, "com.ifinmail", allowInsecure = false)
        val e = assertFailsWith<UpdateException> { strict.check(device) }
        assertEquals(UpdateFailure.REJECTED, e.failure)
        assertTrue("secure" in e.message)
    }

    @Test
    fun anUnreachableServerIsANetworkFailure() {
        val dead = UpdateChecker("http://127.0.0.1:1", "com.ifinmail", allowInsecure = true)
        assertEquals(UpdateFailure.NETWORK, assertFailsWith<UpdateException> { dead.check(device) }.failure)
    }

    // -- downloading -----------------------------------------------------------------------

    @Test
    fun aDownloadIsVerifiedAndGetsItsFinalNameOnlyThen() {
        val release = offer().release
        val progress = mutableListOf<Long>()
        val file = UpdateDownloader(dir).download(release) { done, total ->
            assertEquals(apk.size.toLong(), total)
            progress += done
        }
        assertEquals("ifinmail-5.apk", file.name)
        assertEquals(apkSha, UpdateDownloader.sha256(file))
        assertEquals(apk.size.toLong(), progress.last())
        assertEquals(progress.sorted(), progress, "progress only moves forward")
        assertFalse(File(dir, "ifinmail-5.apk.part").exists())
    }

    @Test
    fun anInterruptedDownloadResumesFromWhatIsOnDisk() {
        val release = offer().release
        val downloader = UpdateDownloader(dir)
        cutAfter = 250_000
        val first = assertFailsWith<UpdateException> { downloader.download(release) }
        assertEquals(UpdateFailure.NETWORK, first.failure)
        val part = File(dir, "ifinmail-5.apk.part")
        assertTrue(part.length() in 1 until apk.size.toLong(), "kept ${part.length()} bytes")

        val kept = part.length()
        cutAfter = -1
        rangeRequests.clear()
        val file = downloader.download(release)
        assertEquals(apkSha, UpdateDownloader.sha256(file))
        assertNotNull(rangeRequests.firstOrNull(), "the retry asked for a range, not the whole file")
        assertEquals("bytes=$kept-", rangeRequests.first())
    }

    @Test
    fun aServerThatIgnoresRangesStillYieldsACorrectFile() {
        val release = offer().release
        val downloader = UpdateDownloader(dir)
        cutAfter = 100_000
        assertFailsWith<UpdateException> { downloader.download(release) }
        cutAfter = -1
        honourRange = false
        val file = downloader.download(release)
        assertEquals(apkSha, UpdateDownloader.sha256(file))
    }

    @Test
    fun aFileThatDoesNotMatchItsChecksumIsDeletedAndNeverKeptUnderTheFinalName() {
        served = apk.copyOf().also { it[1234] = (it[1234] + 1).toByte() } // one flipped byte
        val release = offer().release
        val e = assertFailsWith<UpdateException> { UpdateDownloader(dir).download(release) }
        assertEquals(UpdateFailure.INTEGRITY, e.failure)
        assertEquals(emptyList(), dir.listFiles()!!.map { it.name })
    }

    @Test
    fun aServerSendingMoreThanAnnouncedIsStopped() {
        served = apk + ByteArray(5000)
        val e = assertFailsWith<UpdateException> { UpdateDownloader(dir).download(offer().release) }
        assertTrue(e.failure == UpdateFailure.INTEGRITY || e.failure == UpdateFailure.BAD_RESPONSE)
        assertFalse(File(dir, "ifinmail-5.apk").exists())
    }

    @Test
    fun aMissingFileIsABadResponseNotACrash() {
        apkStatus = 404
        val e = assertFailsWith<UpdateException> { UpdateDownloader(dir).download(offer().release) }
        assertEquals(UpdateFailure.BAD_RESPONSE, e.failure)
    }

    @Test
    fun cancellingStopsTheTransferAndKeepsTheProgress() {
        val release = offer().release
        var chunks = 0
        val e = assertFailsWith<UpdateException> {
            UpdateDownloader(dir).download(release, isCancelled = { ++chunks > 3 })
        }
        assertEquals(UpdateFailure.CANCELLED, e.failure)
        assertFalse(File(dir, "ifinmail-5.apk").exists())
    }

    @Test
    fun anAlreadyVerifiedDownloadIsReusedWithoutTouchingTheNetwork() {
        val release = offer().release
        val downloader = UpdateDownloader(dir)
        downloader.download(release)
        rangeRequests.clear()
        server.removeContext("/media/app.apk") // a second fetch would now fail
        val again = downloader.download(release)
        assertEquals(release.sha256, UpdateDownloader.sha256(again))
        assertTrue(rangeRequests.isEmpty())
    }

    @Test
    fun cleanupKeepsOnlyTheWantedBuild() {
        File(dir, "ifinmail-4.apk").writeText("old")
        File(dir, "ifinmail-5.apk.part").writeText("partial")
        File(dir, "unrelated.txt").writeText("keep")
        UpdateDownloader(dir).cleanup(keepVersionCode = 5)
        assertEquals(listOf("ifinmail-5.apk.part", "unrelated.txt"), dir.list()!!.sorted())
    }
}
