package com.ifinmail.mail

import com.ifinmail.mail.mime.Encodings
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class EncodingsTest {

    @Test
    fun `quoted printable decode handles soft breaks and hex`() {
        val input = "H=C3=A9llo=\r\n world".toByteArray(Charsets.ISO_8859_1)
        val decoded = Encodings.quotedPrintableDecode(input)
        val text = String(decoded, Charsets.UTF_8)
        assertEquals("Héllo world", text)
    }

    @Test
    fun `quoted printable roundtrip preserves unicode`() {
        val original = "Ünïcode — line one\r\nline two = equals\r\n\ttrailing tab "
        val encoded = Encodings.quotedPrintableEncode(original)
        val decoded = String(Encodings.quotedPrintableDecode(encoded.toByteArray(Charsets.ISO_8859_1)), Charsets.UTF_8)
        assertEquals(original, decoded)
    }

    @Test
    fun `quoted printable encodes trailing whitespace before break`() {
        val encoded = Encodings.quotedPrintableEncode("hello \r\nworld")
        assertTrue(encoded.startsWith("hello=20"))
    }

    @Test
    fun `encoded word base64 decodes utf8 subject`() {
        val header = "=?UTF-8?B?SMOpbGxvIFfDtnJsZA==?="
        assertEquals("Héllo Wörld", Encodings.decodeEncodedWords(header))
    }

    @Test
    fun `encoded word quoted printable decodes`() {
        val header = "=?utf-8?q?a_b=C3=A4?="
        assertEquals("a bä", Encodings.decodeEncodedWords(header))
    }

    @Test
    fun `adjacent encoded words collapse whitespace`() {
        val header = "=?UTF-8?B?SGVsbG8=?=   =?UTF-8?B?V29ybGQ=?="
        assertEquals("HelloWorld", Encodings.decodeEncodedWords(header))
    }

    @Test
    fun `encode header value only when necessary`() {
        assertEquals("plain ascii", Encodings.encodeHeaderValueIfNecessary("plain ascii"))
        val encoded = Encodings.encodeHeaderValueIfNecessary("héllo")
        assertTrue(encoded.startsWith("=?UTF-8?B?"))
        assertEquals("héllo", Encodings.decodeEncodedWords(encoded))
    }

    @Test
    fun `lenient base64 tolerates newlines`() {
        val data = byteArrayOf(0, 1, 2, 250.toByte())
        val encoded = Encodings.base64Encode(data)
            .chunked(2).joinToString("\r\n")
        assertTrue(data.contentEquals(Encodings.base64DecodeLenient(encoded)))
    }
}
