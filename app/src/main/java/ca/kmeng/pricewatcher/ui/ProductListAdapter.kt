package ca.kmeng.pricewatcher.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import ca.kmeng.pricewatcher.R
import ca.kmeng.pricewatcher.data.ProductEntity

class ProductListAdapter : ListAdapter<ProductEntity, ProductListAdapter.ProductViewHolder>(DIFF) {

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ProductViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_product, parent, false)
        return ProductViewHolder(view)
    }

    override fun onBindViewHolder(holder: ProductViewHolder, position: Int) {
        holder.bind(getItem(position))
    }

    class ProductViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val nameText: TextView = itemView.findViewById(R.id.productName)
        private val storeText: TextView = itemView.findViewById(R.id.productStore)
        private val priceText: TextView = itemView.findViewById(R.id.productPrice)

        fun bind(product: ProductEntity) {
            nameText.text = product.name
            storeText.text = product.storeName ?: "Unknown store"
            priceText.text = if (product.currentPrice != null) {
                "${product.currentPrice} ${product.currency}"
            } else {
                "No price yet"
            }
        }
    }

    companion object {
        private val DIFF = object : DiffUtil.ItemCallback<ProductEntity>() {
            override fun areItemsTheSame(old: ProductEntity, new: ProductEntity) = old.id == new.id
            override fun areContentsTheSame(old: ProductEntity, new: ProductEntity) = old == new
        }
    }
}
