package ca.kmeng.persianocr.net

import android.content.ContentResolver
import android.net.Uri
import org.json.JSONObject
import java.io.BufferedOutputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.net.UnknownHostException
import java.util.UUID
import javax.net.ssl.SSLException

/** One file to upload: its display name, its bytes source, and its MIME type. */
data class UploadFile(
    val name: String,
    val mimeType: String,
    val openStream: () -> java.io.InputStream,
    val length: Long = -1L,
)

data class OcrOptions(
    val verify: Boolean = true,
    val normalize: Boolean = true,
    val pageNumbers: Boolean = true,
    val passes: Int = 2,
)

data class OcrResult(
    val text: String,
    val confidencePercent: Double,
    val words: Int,
    val pages: Int,
    val corrections: Int,
    val lowConfidencePages: List<Int>,
    val log: List<String>,
)

sealed class OcrOutcome {
    data class Success(val result: OcrResult) : OcrOutcome()
    data class Failure(val reason: String) : OcrOutcome()
}

sealed class ConnectionCheck {
    data class Ok(val detail: String) : ConnectionCheck()
    data class Failed(val reason: String) : ConnectionCheck()
}

/**
 * Talks to the `persian-ocr serve` HTTP endpoint — nothing more. The API key
 * or Claude Code login that actually does the OCR lives on that server, never
 * in this app; the phone only uploads images and downloads text.
 */
object OcrClient {

    private const val READ_TIMEOUT_MS = 6 * 60 * 1000 // verification legitimately takes minutes
    private const val CONNECT_TIMEOUT_MS = 15 * 1000

    fun normalizeBaseUrl(input: String): String? {
        var url = input.trim()
        if (url.isEmpty()) return null
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://$url"
        }
        return url.trimEnd('/')
    }

    fun testConnection(baseUrl: String): ConnectionCheck {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(baseUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = CONNECT_TIMEOUT_MS
            }
            val code = connection.responseCode
            if (code in 200..299) {
                ConnectionCheck.Ok("HTTP $code")
            } else {
                ConnectionCheck.Failed("server replied HTTP $code")
            }
        } catch (e: SocketTimeoutException) {
            ConnectionCheck.Failed("timed out — is the server running and reachable?")
        } catch (e: UnknownHostException) {
            ConnectionCheck.Failed("could not resolve that address")
        } catch (e: SSLException) {
            ConnectionCheck.Failed("TLS error: ${e.message}")
        } catch (e: Exception) {
            ConnectionCheck.Failed("${e.javaClass.simpleName}: ${e.message}")
        } finally {
            connection?.disconnect()
        }
    }

    /** Blocking call — run this off the main thread. */
    fun convert(baseUrl: String, files: List<UploadFile>, options: OcrOptions): OcrOutcome {
        if (files.isEmpty()) return OcrOutcome.Failure("no files to send")

        val boundary = "PersianOcr-${UUID.randomUUID()}"
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL("$baseUrl/convert").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
                setChunkedStreamingMode(64 * 1024)
            }

            BufferedOutputStream(connection.outputStream).use { out ->
                writeField(out, boundary, "verify", if (options.verify) "1" else "0")
                writeField(out, boundary, "normalize", if (options.normalize) "1" else "0")
                writeField(out, boundary, "page_numbers", if (options.pageNumbers) "1" else "0")
                writeField(out, boundary, "passes", options.passes.toString())
                for (file in files) {
                    writeFilePart(out, boundary, file)
                }
                out.write("--$boundary--\r\n".toByteArray(Charsets.UTF_8))
                out.flush()
            }

            val code = connection.responseCode
            val body = (if (code in 200..299) connection.inputStream else connection.errorStream)
                ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()

            if (code !in 200..299) {
                val serverMessage = runCatching { JSONObject(body).optString("error") }.getOrNull()
                return OcrOutcome.Failure(
                    if (!serverMessage.isNullOrBlank()) serverMessage else "server returned HTTP $code"
                )
            }
            OcrOutcome.Success(parseResult(body))
        } catch (e: SocketTimeoutException) {
            OcrOutcome.Failure("timed out waiting for the server — try fewer passes or turn verification off")
        } catch (e: UnknownHostException) {
            OcrOutcome.Failure("could not resolve that address")
        } catch (e: SSLException) {
            OcrOutcome.Failure("TLS error: ${e.message}")
        } catch (e: Exception) {
            OcrOutcome.Failure("${e.javaClass.simpleName}: ${e.message}")
        } finally {
            connection?.disconnect()
        }
    }

    private fun writeField(out: OutputStream, boundary: String, name: String, value: String) {
        out.write("--$boundary\r\n".toByteArray(Charsets.UTF_8))
        out.write("Content-Disposition: form-data; name=\"$name\"\r\n\r\n".toByteArray(Charsets.UTF_8))
        out.write(value.toByteArray(Charsets.UTF_8))
        out.write("\r\n".toByteArray(Charsets.UTF_8))
    }

    private fun writeFilePart(out: OutputStream, boundary: String, file: UploadFile) {
        out.write("--$boundary\r\n".toByteArray(Charsets.UTF_8))
        out.write(
            "Content-Disposition: form-data; name=\"files\"; filename=\"${file.name}\"\r\n"
                .toByteArray(Charsets.UTF_8)
        )
        out.write("Content-Type: ${file.mimeType}\r\n\r\n".toByteArray(Charsets.UTF_8))
        file.openStream().use { input -> input.copyTo(out) }
        out.write("\r\n".toByteArray(Charsets.UTF_8))
    }

    private fun parseResult(body: String): OcrResult {
        val json = JSONObject(body)
        val lowConfidence = json.optJSONArray("low_confidence_pages")?.let { array ->
            (0 until array.length()).map { array.getInt(it) }
        } ?: emptyList()
        val log = json.optJSONArray("log")?.let { array ->
            (0 until array.length()).map { array.getString(it) }
        } ?: emptyList()
        return OcrResult(
            text = json.optString("text"),
            confidencePercent = json.optDouble("confidence", 0.0) * 100.0,
            words = json.optInt("words"),
            pages = json.optInt("pages"),
            corrections = json.optInt("corrections"),
            lowConfidencePages = lowConfidence,
            log = log,
        )
    }
}

/** Wraps a content:// picker result as an [UploadFile], resolving its display name and type. */
fun uploadFileFrom(resolver: ContentResolver, uri: Uri, fallbackIndex: Int): UploadFile {
    var displayName: String? = null
    var size = -1L
    resolver.query(uri, null, null, null, null)?.use { cursor ->
        val nameIndex = cursor.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
        val sizeIndex = cursor.getColumnIndex(android.provider.OpenableColumns.SIZE)
        if (cursor.moveToFirst()) {
            if (nameIndex >= 0) displayName = cursor.getString(nameIndex)
            if (sizeIndex >= 0) size = cursor.getLong(sizeIndex)
        }
    }
    val mimeType = resolver.getType(uri) ?: "application/octet-stream"
    val extension = when {
        mimeType.contains("pdf") -> "pdf"
        mimeType.contains("png") -> "png"
        mimeType.contains("webp") -> "webp"
        mimeType.contains("jpeg") || mimeType.contains("jpg") -> "jpg"
        else -> "bin"
    }
    val name = displayName ?: "page-$fallbackIndex.$extension"
    return UploadFile(
        name = name,
        mimeType = mimeType,
        openStream = { resolver.openInputStream(uri) ?: error("could not open $uri") },
        length = size,
    )
}
