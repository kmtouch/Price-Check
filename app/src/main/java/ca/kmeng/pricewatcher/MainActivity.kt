package ca.kmeng.pricewatcher

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import ca.kmeng.pricewatcher.data.AppDatabase
import ca.kmeng.pricewatcher.data.ProductRepository
import ca.kmeng.pricewatcher.ui.AddProductActivity
import ca.kmeng.pricewatcher.ui.ProductListAdapter
import com.google.android.material.floatingactionbutton.FloatingActionButton
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var repository: ProductRepository
    private lateinit var adapter: ProductListAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val db = AppDatabase.getInstance(applicationContext)
        repository = ProductRepository(db.productDao(), db.priceRecordDao())

        adapter = ProductListAdapter()
        val recyclerView = findViewById<RecyclerView>(R.id.productList)
        recyclerView.layoutManager = LinearLayoutManager(this)
        recyclerView.adapter = adapter

        findViewById<FloatingActionButton>(R.id.addProductFab).setOnClickListener {
            startActivity(Intent(this, AddProductActivity::class.java))
        }

        lifecycleScope.launch {
            repository.getAllProducts().collect { products ->
                adapter.submitList(products)
            }
        }
    }
}
