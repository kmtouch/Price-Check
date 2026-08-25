package ca.kmeng.persianocr.net

import android.content.Context
import androidx.core.content.edit

/** Small SharedPreferences wrapper. No API key ever lives here — only the
 * server address and conversion options; the server owns the credentials. */
object Prefs {
    private const val FILE = "persian_ocr_prefs"
    private const val KEY_SERVER_URL = "server_url"
    private const val KEY_VERIFY = "opt_verify"
    private const val KEY_NORMALIZE = "opt_normalize"
    private const val KEY_PAGE_NUMBERS = "opt_page_numbers"
    private const val KEY_STRIP_HEADERS = "opt_strip_headers"
    private const val KEY_PASSES = "opt_passes"
    private const val KEY_PENDING_JOB_ID = "pending_job_id"
    private const val KEY_PENDING_JOB_SERVER = "pending_job_server"

    fun serverUrl(context: Context): String =
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE).getString(KEY_SERVER_URL, "") ?: ""

    fun setServerUrl(context: Context, url: String) {
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit { putString(KEY_SERVER_URL, url) }
    }

    fun options(context: Context): OcrOptions {
        val prefs = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)
        return OcrOptions(
            verify = prefs.getBoolean(KEY_VERIFY, true),
            normalize = prefs.getBoolean(KEY_NORMALIZE, true),
            pageNumbers = prefs.getBoolean(KEY_PAGE_NUMBERS, true),
            stripHeaders = prefs.getBoolean(KEY_STRIP_HEADERS, true),
            passes = prefs.getInt(KEY_PASSES, 2),
        )
    }

    fun setOptions(context: Context, options: OcrOptions) {
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit {
            putBoolean(KEY_VERIFY, options.verify)
            putBoolean(KEY_NORMALIZE, options.normalize)
            putBoolean(KEY_PAGE_NUMBERS, options.pageNumbers)
            putBoolean(KEY_STRIP_HEADERS, options.stripHeaders)
            putInt(KEY_PASSES, options.passes)
        }
    }

    /** A job survives on the server after the app is closed — a document can
     * take far longer to convert than a phone stays in the foreground. These
     * two remember which job (and against which server) to resume polling
     * the next time the app opens. */
    fun pendingJob(context: Context): JobHandle? {
        val prefs = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)
        val jobId = prefs.getString(KEY_PENDING_JOB_ID, null) ?: return null
        val server = prefs.getString(KEY_PENDING_JOB_SERVER, null)
        if (server != serverUrl(context)) return null // server address changed since; not resumable
        return JobHandle(jobId)
    }

    fun setPendingJob(context: Context, job: JobHandle?) {
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit {
            if (job == null) {
                remove(KEY_PENDING_JOB_ID)
                remove(KEY_PENDING_JOB_SERVER)
            } else {
                putString(KEY_PENDING_JOB_ID, job.jobId)
                putString(KEY_PENDING_JOB_SERVER, serverUrl(context))
            }
        }
    }
}
