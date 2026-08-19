package ca.kmeng.pricewatcher.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface PriceRecordDao {
    @Insert
    suspend fun insert(record: PriceRecordEntity): Long

    @Query("SELECT * FROM price_records WHERE productId = :productId ORDER BY timestamp ASC")
    fun getForProduct(productId: Long): Flow<List<PriceRecordEntity>>

    @Query("SELECT * FROM price_records WHERE productId = :productId ORDER BY timestamp DESC LIMIT 1")
    suspend fun getLatestForProduct(productId: Long): PriceRecordEntity?
}
