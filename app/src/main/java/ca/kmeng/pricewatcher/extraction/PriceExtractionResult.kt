package ca.kmeng.pricewatcher.extraction

data class PriceExtractionResult(
    val success: Boolean,
    val price: Double? = null,
    val currency: String = "CAD",
    val productName: String? = null,
    val imageUrl: String? = null,
    val storeName: String? = null,
    val strategyUsed: String? = null,
    val failureReason: String? = null
)
