package ca.kmeng.pricewatcher.data

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "products")
data class ProductEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val url: String,
    val name: String,
    val storeName: String?,
    val imageUrl: String?,
    val currentPrice: Double?,
    val currency: String = "CAD",
    val checkIntervalHours: Int = 8,
    val createdAt: Long = System.currentTimeMillis(),
    val lastCheckedAt: Long? = null,
    val nextCheckAt: Long? = null,
    val notificationsEnabled: Boolean = true
)
