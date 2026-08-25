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

/** Extensions the server's SUPPORTED_SUFFIXES (persian_ocr/ingest.py) accepts. */
private val RECOGNIZED_EXTENSIONS =
    setOf("pdf", "png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "gif")

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
    val stripHeaders: Boolean = true,
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

/** A conversion runs on the server as a background job — a large document can
 * take far longer than any one HTTP request should stay open, especially from
 * a phone that may lock its screen or lose Wi-Fi mid-upload. Submitting hands
 * back a [JobHandle] immediately; the actual OCR is tracked by polling. */
data class JobHandle(val jobId: String)

sealed class SubmitOutcome {
    data class Submitted(val job: JobHandle) : SubmitOutcome()
    data class Failure(val reason: String) : SubmitOutcome()
}

sealed class JobStatus {
    data class Running(val pagesDone: Int, val pagesTotal: Int?, val lastLogLine: String?) : JobStatus()
    data class Done(val result: OcrResult) : JobStatus()
    data class Failed(val reason: String) : JobStatus()
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

    // Submitting and polling are both meant to return quickly — the actual
    // OCR work happens on the server between polls, not inside either call.
    private const val SUBMIT_READ_TIMEOUT_MS = 60 * 1000
    private const val POLL_READ_TIMEOUT_MS = 20 * 1000
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

    /** Uploads the files and starts the job. Blocking — run off the main thread. */
    fun submit(baseUrl: String, files: List<UploadFile>, options: OcrOptions): SubmitOutcome {
        if (files.isEmpty()) return SubmitOutcome.Failure("no files to send")

        val boundary = "PersianOcr-${UUID.randomUUID()}"
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL("$baseUrl/convert").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = SUBMIT_READ_TIMEOUT_MS
                setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
                setChunkedStreamingMode(64 * 1024)
            }

            BufferedOutputStream(connection.outputStream).use { out ->
                writeField(out, boundary, "verify", if (options.verify) "1" else "0")
                writeField(out, boundary, "normalize", if (options.normalize) "1" else "0")
                writeField(out, boundary, "page_numbers", if (options.pageNumbers) "1" else "0")
                writeField(out, boundary, "strip_headers", if (options.stripHeaders) "1" else "0")
                writeField(out, boundary, "passes", options.passes.toString())
                for (file in files) {
                    writeFilePart(out, boundary, file)
                }
                out.write("--$boundary--\r\n".toByteArray(Charsets.UTF_8))
                out.flush()
            }

            val code = connection.responseCode
            val body = readBody(connection, code)
            if (code !in 200..299) {
                return SubmitOutcome.Failure(errorMessageFrom(body, code))
            }
            SubmitOutcome.Submitted(JobHandle(JSONObject(body).getString("job_id")))
        } catch (e: SocketTimeoutException) {
            SubmitOutcome.Failure("timed out uploading — check the connection and try again")
        } catch (e: UnknownHostException) {
            SubmitOutcome.Failure("could not resolve that address")
        } catch (e: SSLException) {
            SubmitOutcome.Failure("TLS error: ${e.message}")
        } catch (e: Exception) {
            SubmitOutcome.Failure("${e.javaClass.simpleName}: ${e.message}")
        } finally {
            connection?.disconnect()
        }
    }

    /** Checks a job's current state once. Blocking — run off the main thread. */
    fun poll(baseUrl: String, job: JobHandle): JobStatus {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL("$baseUrl/jobs/${job.jobId}").openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = POLL_READ_TIMEOUT_MS
            }
            val code = connection.responseCode
            val body = readBody(connection, code)
            if (code !in 200..299) {
                return JobStatus.Failed(errorMessageFrom(body, code))
            }

            val json = JSONObject(body)
            when (json.optString("status")) {
                "done" -> JobStatus.Done(parseResult(json.getJSONObject("result")))
                "error" -> JobStatus.Failed(json.optString("error").ifBlank { "the server reported an error" })
                else -> {
                    val log = json.optJSONArray("log")
                    val lastLine = if (log != null && log.length() > 0) log.getString(log.length() - 1) else null
                    JobStatus.Running(
                        pagesDone = json.optInt("pages_done", 0),
                        pagesTotal = if (json.isNull("pages_total")) null else json.optInt("pages_total"),
                        lastLogLine = lastLine,
                    )
                }
            }
        } catch (e: SocketTimeoutException) {
            JobStatus.Failed("timed out checking progress — will retry")
        } catch (e: UnknownHostException) {
            JobStatus.Failed("could not resolve that address")
        } catch (e: SSLException) {
            JobStatus.Failed("TLS error: ${e.message}")
        } catch (e: Exception) {
            JobStatus.Failed("${e.javaClass.simpleName}: ${e.message}")
        } finally {
            connection?.disconnect()
        }
    }

    private fun readBody(connection: HttpURLConnection, code: Int): String =
        (if (code in 200..299) connection.inputStream else connection.errorStream)
            ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()

    private fun errorMessageFrom(body: String, code: Int): String {
        val serverMessage = runCatching { JSONObject(body).optString("error") }.getOrNull()
        return if (!serverMessage.isNullOrBlank()) serverMessage else "server returned HTTP $code"
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

    private fun parseResult(json: JSONObject): OcrResult {
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
    var rawDisplayName: String? = null
    var size = -1L
    resolver.query(uri, null, null, null, null)?.use { cursor ->
        val nameIndex = cursor.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
        val sizeIndex = cursor.getColumnIndex(android.provider.OpenableColumns.SIZE)
        if (cursor.moveToFirst()) {
            if (nameIndex >= 0) rawDisplayName = cursor.getString(nameIndex)
            if (sizeIndex >= 0) size = cursor.getLong(sizeIndex)
        }
    }
    // Read into a val: rawDisplayName is a var mutated inside the query lambda above, so
    // Kotlin won't smart-cast it to non-null below even after an explicit null check.
    val displayName: String? = rawDisplayName
    val mimeType = resolver.getType(uri) ?: "application/octet-stream"
    val mimeExtension = when {
        mimeType.contains("pdf") -> "pdf"
        mimeType.contains("png") -> "png"
        mimeType.contains("webp") -> "webp"
        mimeType.contains("jpeg") || mimeType.contains("jpg") -> "jpg"
        mimeType.contains("bmp") -> "bmp"
        mimeType.contains("tiff") -> "tif"
        mimeType.contains("gif") -> "gif"
        else -> "bin"
    }
    // Some content providers (gallery apps, cloud storage, Google Photos) hand back a
    // DISPLAY_NAME with no extension, or one the server's whitelist doesn't recognize,
    // even though the MIME type correctly identifies it as a supported image/PDF. The
    // server keys its supported-file check purely off the filename suffix, so trusting
    // an extension-less or unrecognized display name here silently gets the whole
    // upload rejected with "no supported files were uploaded". Only keep the display
    // name's own extension when it is one the server actually accepts.
    val displayExtension = displayName?.substringAfterLast('.', "")?.lowercase()
    val name = when {
        displayExtension != null && displayExtension in RECOGNIZED_EXTENSIONS ->
            displayName!!
        displayName != null ->
            "${displayName.substringBeforeLast('.')}.$mimeExtension"
        else ->
            "page-$fallbackIndex.$mimeExtension"
    }
    return UploadFile(
        name = name,
        mimeType = mimeType,
        openStream = { resolver.openInputStream(uri) ?: error("could not open $uri") },
        length = size,
    )
}
