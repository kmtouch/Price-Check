package ca.kmeng.pricewatcher.ui

import android.os.Bundle
import android.webkit.WebView
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import ca.kmeng.pricewatcher.R
import ca.kmeng.pricewatcher.data.AppDatabase
import ca.kmeng.pricewatcher.data.PriceRecordEntity
import ca.kmeng.pricewatcher.data.ProductEntity
import ca.kmeng.pricewatcher.data.ProductRepository
import ca.kmeng.pricewatcher.extraction.FetchResult
import ca.kmeng.pricewatcher.extraction.HtmlFetcher
import ca.kmeng.pricewatcher.extraction.PriceExtractionResult
import ca.kmeng.pricewatcher.extraction.PriceExtractor
import ca.kmeng.pricewatcher.extraction.WebViewPriceFetcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

class AddProductActivity : AppCompatActivity() {

    private lateinit var repository: ProductRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_add_product)

        val db = AppDatabase.getInstance(applicationContext)
        repository = ProductRepository(db.productDao(), db.priceRecordDao())

        val urlInput = findViewById<EditText>(R.id.urlInput)
        val saveButton = findViewById<Button>(R.id.saveButton)
        val statusText = findViewById<TextView>(R.id.addStatusText)
        val progressBar = findViewById<ProgressBar>(R.id.addProgressBar)
        val hiddenWebView = findViewById<WebView>(R.id.hiddenWebView)

        saveButton.setOnClickListener {
            val url = urlInput.text.toString().trim()
            if (url.isBlank() || !(url.startsWith("http://") || url.startsWith("https://"))) {
                statusText.text = "Enter a valid URL starting with http:// or https://"
                return@setOnClickListener
            }

            progressBar.visibility = android.view.View.VISIBLE
            saveButton.isEnabled = false

            lifecycleScope.launch {
                statusText.text = "Fetching page (static)…"

                var result: PriceExtractionResult? = null
                var staticFailureReason: String? = null

                val fetchResult = withContext(Dispatchers.IO) { HtmlFetcher.fetch(url) }
                when (fetchResult) {
                    is FetchResult.Success -> {
                        result = withContext(Dispatchers.IO) {
                            PriceExtractor.extractFromHtml(url, fetchResult.html)
                        }
                    }
                    is FetchResult.Failure -> {
                        staticFailureReason = fetchResult.reason
                    }
                }

                if (result == null || !result.success) {
                    statusText.text = "Static fetch " +
                        (staticFailureReason?.let { "failed ($it)" } ?: "found no price") +
                        " — trying JS-rendered fetch…"

                    val renderedHtml = withTimeoutOrNull(25000) {
                        WebViewPriceFetcher.fetchRenderedHtml(hiddenWebView, url)
                    }

                    if (renderedHtml != null) {
                        val jsResult = withContext(Dispatchers.IO) {
                            PriceExtractor.extractFromHtml(url, renderedHtml)
                        }
                        result = if (jsResult.success) {
                            jsResult.copy(strategyUsed = "webview:${jsResult.strategyUsed}")
                        } else {
                            jsResult
                        }
                    } else if (result == null) {
                        result = PriceExtractionResult(
                            success = false,
                            failureReason = "Static fetch: ${staticFailureReason ?: "unknown error"}. " +
                                "WebView fetch: timed out or returned no content."
                        )
                    }
                }

                progressBar.visibility = android.view.View.GONE
                saveButton.isEnabled = true

                val finalResult = result
                if (finalResult == null || !finalResult.success || finalResult.price == null) {
                    statusText.text = "Unable to automatically extract the price from this page.\n" +
                        (finalResult?.failureReason ?: "Unknown failure.")
                    return@launch
                }

                val storeName = try {
                    java.net.URI(url).host?.removePrefix("www.")
                } catch (e: Exception) {
                    null
                }

                val product = ProductEntity(
                    url = url,
                    name = finalResult.productName ?: url,
                    storeName = storeName,
                    imageUrl = finalResult.imageUrl,
                    currentPrice = finalResult.price,
                    currency = finalResult.currency,
                    lastCheckedAt = System.currentTimeMillis()
                )

                val productId = repository.addProduct(product)
                repository.recordPrice(
                    PriceRecordEntity(
                        productId = productId,
                        price = finalResult.price,
                        currency = finalResult.currency,
                        sourceUrl = url
                    )
                )

                statusText.text = "Saved. Price: ${finalResult.price} ${finalResult.currency} (via ${finalResult.strategyUsed})"
                urlInput.setText("")
                finish()
            }
        }
    }
}
