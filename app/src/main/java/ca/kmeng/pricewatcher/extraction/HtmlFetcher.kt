package ca.kmeng.pricewatcher.extraction

import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.net.UnknownHostException
import javax.net.ssl.SSLException

sealed class FetchResult {
    data class Success(val html: String) : FetchResult()
    data class Failure(val reason: String) : FetchResult()
}

object HtmlFetcher {
    private const val USER_AGENT =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    fun fetch(url: String, timeoutMs: Int = 15000): FetchResult {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
                setRequestProperty("User-Agent", USER_AGENT)
                setRequestProperty("Accept", "text/html,application/xhtml+xml")
                setRequestProperty("Accept-Language", "en-CA,en;q=0.9")
                instanceFollowRedirects = true
            }
            val code = connection.responseCode
            if (code in 200..299) {
                FetchResult.Success(connection.inputStream.bufferedReader().use { it.readText() })
            } else {
                FetchResult.Failure("HTTP $code from server — page fetch was rejected or blocked")
            }
        } catch (e: SocketTimeoutException) {
            FetchResult.Failure("Connection timed out after ${timeoutMs}ms")
        } catch (e: UnknownHostException) {
            FetchResult.Failure("Could not resolve host (DNS failure or invalid domain)")
        } catch (e: SSLException) {
            FetchResult.Failure("SSL/TLS error: ${e.message}")
        } catch (e: Exception) {
            FetchResult.Failure("${e.javaClass.simpleName}: ${e.message}")
        } finally {
            connection?.disconnect()
        }
    }
}
