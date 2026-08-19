package ca.kmeng.pricewatcher.data

import kotlinx.coroutines.flow.Flow

class ProductRepository(
    private val productDao: ProductDao,
    private val priceRecordDao: PriceRecordDao
) {
    fun getAllProducts(): Flow<List<ProductEntity>> = productDao.getAll()

    fun getHistory(productId: Long): Flow<List<PriceRecordEntity>> =
        priceRecordDao.getForProduct(productId)

    suspend fun addProduct(product: ProductEntity): Long = productDao.insert(product)

    suspend fun recordPrice(record: PriceRecordEntity) {
        priceRecordDao.insert(record)
    }
}
