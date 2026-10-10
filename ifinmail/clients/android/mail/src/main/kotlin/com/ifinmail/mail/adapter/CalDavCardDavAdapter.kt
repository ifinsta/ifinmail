package com.ifinmail.mail.adapter

import com.ifinmail.core.domain.port.CalendarCapability
import com.ifinmail.core.domain.port.CalendarProbeResult
import com.ifinmail.core.domain.port.ContactCapability
import com.ifinmail.core.domain.port.ContactProbeResult
import java.net.HttpURLConnection
import java.net.URL
import java.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private fun davProbe(url: String, email: String, password: String, timeoutMs: Int): Pair<Boolean, String> {
    var connection: HttpURLConnection? = null
    return try {
        val target = URL(if (url.startsWith("http")) url else "https://$url")
        connection = target.openConnection() as HttpURLConnection
        connection.requestMethod = "PROPFIND"
        connection.connectTimeout = timeoutMs
        connection.readTimeout = timeoutMs
        val credentials = Base64.getEncoder().encodeToString("$email:$password".toByteArray())
        connection.setRequestProperty("Authorization", "Basic $credentials")
        connection.setRequestProperty("Depth", "0")
        connection.setRequestProperty("Content-Type", "application/xml; charset=utf-8")
        connection.doOutput = true
        connection.outputStream.use {
            it.write("<?xml version=\"1.0\"?><d:propfind xmlns:d=\"DAV:\"><d:prop><d:current-user-principal/></d:prop></d:propfind>".toByteArray())
        }
        val code = connection.responseCode
        when (code) {
            200, 207 -> true to "DAV endpoint responded $code"
            401 -> true to "Endpoint reachable; authentication required"
            else -> false to "DAV endpoint responded $code"
        }
    } catch (e: Exception) {
        false to "DAV endpoint unreachable: ${e.message}"
    } finally {
        connection?.disconnect()
    }
}

class CalDavProbeAdapter(
    private val baseHost: String,
    private val email: String,
    private val password: String,
    private val timeoutMs: Int = 5000
) : CalendarCapability {

    override suspend fun probe(): CalendarProbeResult = withContext(Dispatchers.IO) {
        val (reachable, detail) = davProbe("$baseHost/dav/calendars/", email, password, timeoutMs)
        CalendarProbeResult(reachable, detail)
    }
}

class CardDavProbeAdapter(
    private val baseHost: String,
    private val email: String,
    private val password: String,
    private val timeoutMs: Int = 5000
) : ContactCapability {

    override suspend fun probe(): ContactProbeResult = withContext(Dispatchers.IO) {
        val (reachable, detail) = davProbe("$baseHost/dav/addressbooks/", email, password, timeoutMs)
        ContactProbeResult(reachable, detail)
    }
}
