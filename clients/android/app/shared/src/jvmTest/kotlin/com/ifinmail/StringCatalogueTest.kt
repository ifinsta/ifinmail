package com.ifinmail

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Guards the string catalogue: every translation must define exactly the keys of the base
 * catalogue and use the same format placeholders, so a missing or reordered argument is caught
 * here instead of crashing a screen in another language.
 */
class StringCatalogueTest {

    private val resourcesDir = File("src/commonMain/composeResources")

    private fun entries(file: File): Map<String, String> {
        val text = file.readText()
        val result = linkedMapOf<String, String>()
        Regex("""<string name="([^"]+)">(.*?)</string>""", RegexOption.DOT_MATCHES_ALL)
            .findAll(text).forEach { result[it.groupValues[1]] = it.groupValues[2] }
        Regex("""<string-array name="([^"]+)">(.*?)</string-array>""", RegexOption.DOT_MATCHES_ALL)
            .findAll(text).forEach { m ->
                val items = Regex("<item>").findAll(m.groupValues[2]).count()
                result["array:" + m.groupValues[1]] = "items=$items"
            }
        return result
    }

    private fun placeholders(value: String): List<String> =
        Regex("""%\d+\$[sd]""").findAll(value).map { it.value }.sorted().toList()

    private val base: Map<String, String> by lazy { entries(File(resourcesDir, "values/strings.xml")) }

    private val translations: List<File> by lazy {
        resourcesDir.listFiles { f -> f.isDirectory && f.name.startsWith("values-") }.orEmpty()
            .map { File(it, "strings.xml") }
            .filter { it.exists() }
    }

    @Test
    fun baseCatalogueIsNotEmpty() {
        assertTrue(base.size > 100, "expected the full catalogue, found ${base.size} entries")
    }

    @Test
    fun translationsDefineExactlyTheBaseKeys() {
        assertTrue(translations.isNotEmpty(), "no translations found next to the base catalogue")
        translations.forEach { file ->
            val keys = entries(file).keys
            assertEquals(emptySet(), base.keys - keys, "${file.parentFile.name}: missing keys")
            assertEquals(emptySet(), keys - base.keys, "${file.parentFile.name}: unknown keys")
        }
    }

    @Test
    fun translationsKeepFormatPlaceholders() {
        translations.forEach { file ->
            val translated = entries(file)
            val mismatches = base
                .filterKeys { !it.startsWith("array:") }
                .filter { (key, value) -> placeholders(value) != placeholders(translated[key].orEmpty()) }
                .keys
            assertEquals(emptySet<String>(), mismatches, "${file.parentFile.name}: placeholder mismatch")
        }
    }

    @Test
    fun monthArrayHasTwelveItems() {
        assertEquals("items=12", base["array:month_abbreviations"])
        translations.forEach { assertEquals("items=12", entries(it)["array:month_abbreviations"], it.parentFile.name) }
    }
}
