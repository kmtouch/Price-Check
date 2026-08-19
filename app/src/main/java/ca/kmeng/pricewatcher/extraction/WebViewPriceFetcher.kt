package ca.kmeng.pricewatcher.extraction

import android.webkit.WebView
import android.webkit.WebViewClient
import kotlinx.coroutines.suspendCancellableCoroutine
import org.json.JSONTokener
import kotlin.coroutines.resume

object WebViewPriceFetcher {

    private const val RENDER_SETTLE_DELAY_MS = 3000L

    suspend fun fetchRenderedHtml(webView: WebView, url: String): String? =
        suspendCancellableCoroutine { continuation ->
            webView.settings.javaScriptEnabled = true
            webView.settings.domStorageEnabled = true

            webView.webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView, finishedUrl: String) {
                    view.postDelayed({
                        if (!continuation.isActive) return@postDelayed
                        view.evaluateJavascript("document.documentElement.outerHTML") { raw ->
                            val html = decodeJsString(raw)
                            view.stopLoading()
                            view.loadUrl("about:blank")
                            if (continuation.isActive) {
                                continuation.resume(html)
                            }
                        }
                    }, RENDER_SETTLE_DELAY_MS)
                }
            }

            continuation.invokeOnCancellation {
                webView.stopLoading()
            }

            webView.loadUrl(url)
        }

    private fun decodeJsString(raw: String?): String? {
        if (raw == null || raw == "null") return null
        return try {
            JSONTokener(raw).nextValue() as? String
        } catch (e: Exception) {
            null
        }
    }
}
