package ca.kmeng.pricewatcher.ui

import android.os.Bundle
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
import ca.kmeng.pricewatcher.extraction.HtmlFetcher
import ca.kmeng.pricewatcher.extraction.PriceExtractor
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

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

        saveButton.setOnClickListener {
            val url = urlInput.text.toString().trim()
            if (url.isBlank() || !(url.startsWith("http://") || url.startsWith("https://"))) {
                statusText.text = "Enter a valid URL starting with http:// or https://"
                return@setOnClickListener
            }

            progressBar.visibility = android.view.View.VISIBLE
            statusText.text = "Fetching page and extracting price…"
            saveButton.isEnabled = false

            lifecycleScope.launch {
                val result = withContext(Dispatchers.IO) {
                    val html = HtmlFetcher.fetch(url)
                    if (html == null) {
                        null
                    } else {
                        PriceExtractor.extractFromHtml(url, html)
                    }
                }

                progressBar.visibility = android.view.View.GONE
                saveButton.isEnabled = true

                if (result == null) {
                    statusText.text = "Unable to automatically extract the price from this page. " +
                        "(Could not fetch the page — check the URL or your connection.)"
                    return@launch
                }

                if (!result.success || result.price == null) {
                    statusText.text = "Unable to automatically extract the price from this page. " +
                        "(${result.failureReason ?: "no price detected"})"
                    return@launch
                }

                val storeName = try {
                    java.net.URI(url).host?.removePrefix("www.")
                } catch (e: Exception) {
                    null
                }

                val product = ProductEntity(
                    url = url,
                    name = result.productName ?: url,
                    storeName = storeName,
                    imageUrl = result.imageUrl,
                    currentPrice = result.price,
                    currency = result.currency,
                    lastCheckedAt = System.currentTimeMillis()
                )

                val productId = repository.addProduct(product)
                repository.recordPrice(
                    PriceRecordEntity(
                        productId = productId,
                        price = result.price,
                        currency = result.currency,
                        sourceUrl = url
                    )
                )

                statusText.text = "Saved. Price: ${result.price} ${result.currency} (via ${result.strategyUsed})"
                urlInput.setText("")
                finish()
            }
        }
    }
}
