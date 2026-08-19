package ca.kmeng.pricewatcher.extraction

import org.json.JSONArray
import org.json.JSONObject
import org.jsoup.Jsoup
import org.jsoup.nodes.Document
import org.jsoup.nodes.Element
import java.util.regex.Pattern

/**
 * Multi-strategy price extractor. Tries, in order:
 * 1. JSON-LD Product/Offer schema
 * 2. OpenGraph / meta tags
 * 3. Heuristic HTML price elements (excluding struck-through / "was" prices)
 * 4. Regex fallback over visible text
 *
 * Does NOT execute JavaScript — sites that render price client-side will fail
 * every strategy here and need the WebView-based fallback (separate, later).
 */
object PriceExtractor {

    private val CAD_PRICE_PATTERN: Pattern = Pattern.compile(
        "(?:CAD\\s*|C\\$\\s*|\\$\\s*)([0-9]{1,3}(?:,[0-9]{3})*(?:\\.[0-9]{2})?)" +
        "|([0-9]{1,3}(?:,[0-9]{3})*(?:\\.[0-9]{2})?)\\s*CAD"
    )

    private val EXCLUDE_CLASS_KEYWORDS = listOf(
        "was", "old-price", "strike", "msrp", "list-price", "compare-at",
        "shipping", "installment", "financing", "coupon", "saved", "you-save"
    )

    fun extractFromHtml(url: String, html: String): PriceExtractionResult {
        val doc = try {
            Jsoup.parse(html, url)
        } catch (e: Exception) {
            return PriceExtractionResult(success = false, failureReason = "HTML parse failed: ${e.message}")
        }

        extractJsonLd(doc)?.let { return it }
        extractOpenGraph(doc)?.let { return it }
        extractHeuristicHtml(doc)?.let { return it }
        extractRegexFallback(doc)?.let { return it }

        return PriceExtractionResult(
            success = false,
            failureReason = "No price found via JSON-LD, OpenGraph, HTML heuristics, or text scan"
        )
    }

    private fun extractJsonLd(doc: Document): PriceExtractionResult? {
        val scripts = doc.select("script[type=application/ld+json]")
        for (script in scripts) {
            val json = try {
                JSONObject(script.data())
            } catch (e: Exception) {
                continue
            }
            val price = findPriceInJsonLd(json) ?: continue
            return PriceExtractionResult(
                success = true,
                price = price.first,
                currency = price.second ?: "CAD",
                productName = json.optString("name").takeIf { it.isNotBlank() },
                imageUrl = extractJsonLdImage(json),
                strategyUsed = "json-ld"
            )
        }
        return null
    }

    private fun findPriceInJsonLd(json: JSONObject): Pair<Double, String?>? {
        val type = json.opt("@type")
        val isProduct = (type is String && type.equals("Product", ignoreCase = true)) ||
            (type is JSONArray && (0 until type.length()).any {
                (type.opt(it) as? String)?.equals("Product", ignoreCase = true) == true
            })

        if (isProduct && json.has("offers")) {
            val offers = json.get("offers")
            val offer = when (offers) {
                is JSONObject -> offers
                is JSONArray -> if (offers.length() > 0) offers.optJSONObject(0) else null
                else -> null
            }
            offer?.let {
                val priceRaw = it.opt("price") ?: it.opt("lowPrice")
                val priceVal = when (priceRaw) {
                    is Number -> priceRaw.toDouble()
                    is String -> priceRaw.replace(",", "").toDoubleOrNull()
                    else -> null
                }
                if (priceVal != null) {
                    return priceVal to it.optString("priceCurrency").takeIf { c -> c.isNotBlank() }
                }
            }
        }

        if (json.has("@graph")) {
            val graph = json.optJSONArray("@graph")
            if (graph != null) {
                for (i in 0 until graph.length()) {
                    val node = graph.optJSONObject(i) ?: continue
                    findPriceInJsonLd(node)?.let { return it }
                }
            }
        }
        return null
    }

    private fun extractJsonLdImage(json: JSONObject): String? {
        val img = json.opt("image")
        return when (img) {
            is String -> img
            is JSONArray -> if (img.length() > 0) img.optString(0) else null
            is JSONObject -> img.optString("url").takeIf { it.isNotBlank() }
            else -> null
        }
    }

    private fun extractOpenGraph(doc: Document): PriceExtractionResult? {
        val amount = doc.selectFirst("meta[property=og:price:amount]")?.attr("content")
            ?: doc.selectFirst("meta[property=product:price:amount]")?.attr("content")
        val priceVal = amount?.replace(",", "")?.toDoubleOrNull() ?: return null

        val currency = doc.selectFirst("meta[property=og:price:currency]")?.attr("content")
            ?: doc.selectFirst("meta[property=product:price:currency]")?.attr("content")
        val name = doc.selectFirst("meta[property=og:title]")?.attr("content")
        val image = doc.selectFirst("meta[property=og:image]")?.attr("content")

        return PriceExtractionResult(
            success = true,
            price = priceVal,
            currency = currency?.takeIf { it.isNotBlank() } ?: "CAD",
            productName = name?.takeIf { it.isNotBlank() },
            imageUrl = image,
            strategyUsed = "opengraph"
        )
    }

    private fun extractHeuristicHtml(doc: Document): PriceExtractionResult? {
        val candidates = doc.select(
            "[itemprop=price], [class*=price], [id*=price], [data-price], [class*=Price], [id*=Price]"
        )

        val valid = mutableListOf<Pair<Double, Element>>()
        for (el in candidates) {
            val classAndId = (el.className() + " " + el.id()).lowercase()
            if (EXCLUDE_CLASS_KEYWORDS.any { classAndId.contains(it) }) continue
            if (el.tagName().lowercase() in listOf("del", "s", "strike")) continue

            val text = el.attr("content").ifBlank { el.attr("data-price").ifBlank { el.text() } }
            val matcher = CAD_PRICE_PATTERN.matcher(text)
            if (matcher.find()) {
                val raw = matcher.group(1) ?: matcher.group(2)
                val value = raw?.replace(",", "")?.toDoubleOrNull()
                if (value != null && value > 0) {
                    valid.add(value to el)
                }
            }
        }

        if (valid.isEmpty()) return null

        val chosen = valid.minByOrNull { it.first } ?: return null

        return PriceExtractionResult(
            success = true,
            price = chosen.first,
            currency = "CAD",
            productName = doc.selectFirst("h1")?.text(),
            strategyUsed = "heuristic-html"
        )
    }

    private fun extractRegexFallback(doc: Document): PriceExtractionResult? {
        val bodyText = doc.body()?.text() ?: return null
        val matcher = CAD_PRICE_PATTERN.matcher(bodyText)
        if (matcher.find()) {
            val raw = matcher.group(1) ?: matcher.group(2)
            val value = raw?.replace(",", "")?.toDoubleOrNull() ?: return null
            return PriceExtractionResult(
                success = true,
                price = value,
                currency = "CAD",
                productName = doc.selectFirst("h1")?.text() ?: doc.title(),
                strategyUsed = "regex-fallback"
            )
        }
        return null
    }
}
