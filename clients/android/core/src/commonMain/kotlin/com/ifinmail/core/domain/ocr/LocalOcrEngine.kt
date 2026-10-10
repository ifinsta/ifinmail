package com.ifinmail.core.domain.ocr

import com.ifinmail.core.domain.port.OcrService

class LocalOcrEngine : OcrService {
    override suspend fun extractText(bytes: ByteArray, mediaType: String): String {
        // MVP heuristic OCR stub: extracts any ASCII runs from binary (works for text-embedded
        // "scanned" fixtures). Real adapter swap: ML Kit / Tesseract behind the same port.
        val printable = bytes.map { it.toInt() and 0xFF }
            .filter { it == 32 || it == 10 || it == 13 || (it in 33..126) }
        val text = printable.map { it.toChar() }.joinToString("")
        return text.trim().takeIf { it.length >= 3 } ?: ""
    }
}
