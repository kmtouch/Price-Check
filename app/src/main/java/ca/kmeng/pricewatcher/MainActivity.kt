package ca.kmeng.pricewatcher

import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import ca.kmeng.pricewatcher.data.AppDatabase
import ca.kmeng.pricewatcher.data.ProductRepository
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var repository: ProductRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val db = AppDatabase.getInstance(applicationContext)
        repository = ProductRepository(db.productDao(), db.priceRecordDao())

        val statusText = findViewById<TextView>(R.id.statusText)

        lifecycleScope.launch {
            repository.getAllProducts().collect { products ->
                statusText.text = "Price Watcher — DB OK. Tracked products: ${products.size}"
            }
        }
    }
}
