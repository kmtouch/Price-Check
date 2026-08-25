package ca.kmeng.persianocr.ui

import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import ca.kmeng.persianocr.R
import ca.kmeng.persianocr.databinding.ActivityMainBinding
import ca.kmeng.persianocr.net.JobHandle
import ca.kmeng.persianocr.net.JobStatus
import ca.kmeng.persianocr.net.OcrClient
import ca.kmeng.persianocr.net.Prefs
import ca.kmeng.persianocr.net.ResultHolder
import ca.kmeng.persianocr.net.SubmitOutcome
import ca.kmeng.persianocr.net.uploadFileFrom
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/** How often to check on an in-flight job. A page takes at least tens of
 * seconds to read, so there is no benefit to polling faster than this — it
 * would only cost battery and the server a few extra requests. */
private const val POLL_INTERVAL_MS = 2500L

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var chosenUris: List<Uri> = emptyList()
    private var pendingCameraUri: Uri? = null
    private var polling = false

    private val pickFiles = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            uris.forEach { uri ->
                runCatching {
                    contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
            }
            setChosenFiles(uris)
        }
    }

    private val takePicture = registerForActivityResult(ActivityResultContracts.TakePicture()) { success ->
        val uri = pendingCameraUri
        if (success && uri != null) {
            setChosenFiles(listOf(uri))
        }
    }

    private val requestCameraPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) launchCamera() else toast(getString(R.string.camera_permission_denied))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.settingsButton.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }
        binding.pickFilesButton.setOnClickListener {
            pickFiles.launch(arrayOf("application/pdf", "image/*"))
        }
        binding.takePhotoButton.setOnClickListener { requestCameraThenLaunch() }
        binding.convertButton.setOnClickListener { convert() }
    }

    override fun onResume() {
        super.onResume()
        val serverUrl = Prefs.serverUrl(this)
        binding.serverStatusText.text = if (serverUrl.isBlank()) {
            getString(R.string.no_server_set)
        } else {
            serverUrl
        }
        updateConvertEnabled()
        resumePendingJobIfAny()
    }

    private fun resumePendingJobIfAny() {
        if (polling) return
        val baseUrl = OcrClient.normalizeBaseUrl(Prefs.serverUrl(this)) ?: return
        val job = Prefs.pendingJob(this) ?: return
        setBusy(true)
        binding.progressLabel.text = getString(R.string.resuming_job)
        trackJob(baseUrl, job)
    }

    private fun setChosenFiles(uris: List<Uri>) {
        chosenUris = uris
        binding.filesChosenText.text = if (uris.isEmpty()) {
            getString(R.string.no_files_chosen)
        } else {
            getString(R.string.files_chosen, uris.size)
        }
        updateConvertEnabled()
    }

    private fun updateConvertEnabled() {
        binding.convertButton.isEnabled = !polling && chosenUris.isNotEmpty() && Prefs.serverUrl(this).isNotBlank()
    }

    private fun requestCameraThenLaunch() {
        val granted = ContextCompat.checkSelfPermission(
            this, android.Manifest.permission.CAMERA
        ) == PackageManager.PERMISSION_GRANTED
        if (granted) launchCamera() else requestCameraPermission.launch(android.Manifest.permission.CAMERA)
    }

    private fun launchCamera() {
        val imagesDir = File(cacheDir, "images").apply { mkdirs() }
        val file = File(imagesDir, "capture-${System.currentTimeMillis()}.jpg")
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
        pendingCameraUri = uri
        takePicture.launch(uri)
    }

    private fun convert() {
        val baseUrl = OcrClient.normalizeBaseUrl(Prefs.serverUrl(this))
        if (baseUrl == null) {
            toast(getString(R.string.no_server_set))
            return
        }
        setBusy(true)
        binding.progressLabel.text = getString(R.string.converting)
        val resolver = contentResolver
        val files = chosenUris.mapIndexed { index, uri -> uploadFileFrom(resolver, uri, index + 1) }
        val options = Prefs.options(this)

        lifecycleScope.launch {
            val outcome = withContext(Dispatchers.IO) { OcrClient.submit(baseUrl, files, options) }
            when (outcome) {
                is SubmitOutcome.Submitted -> {
                    Prefs.setPendingJob(this@MainActivity, outcome.job)
                    trackJob(baseUrl, outcome.job)
                }
                is SubmitOutcome.Failure -> {
                    setBusy(false)
                    showError(getString(R.string.upload_failed, outcome.reason))
                }
            }
        }
    }

    /** Polls a job to completion, updating progress as it goes. Safe to call
     * for a job this launch already submitted, or one resumed from a prior
     * app session — either way the job itself lives entirely on the server. */
    private fun trackJob(baseUrl: String, job: JobHandle) {
        polling = true
        lifecycleScope.launch {
            while (true) {
                val status = withContext(Dispatchers.IO) { OcrClient.poll(baseUrl, job) }
                when (status) {
                    is JobStatus.Running -> {
                        renderProgress(status)
                        delay(POLL_INTERVAL_MS)
                    }
                    is JobStatus.Done -> {
                        Prefs.setPendingJob(this@MainActivity, null)
                        polling = false
                        setBusy(false)
                        ResultHolder.result = status.result
                        startActivity(Intent(this@MainActivity, ResultActivity::class.java))
                        return@launch
                    }
                    is JobStatus.Failed -> {
                        Prefs.setPendingJob(this@MainActivity, null)
                        polling = false
                        setBusy(false)
                        showError(getString(R.string.upload_failed, status.reason))
                        return@launch
                    }
                }
            }
        }
    }

    private fun renderProgress(status: JobStatus.Running) {
        val total = status.pagesTotal
        if (total != null && total > 0) {
            binding.progressLabel.text = getString(R.string.page_progress, status.pagesDone, total)
            binding.progressBarDeterminate.visibility = View.VISIBLE
            binding.progressBarDeterminate.progress = (100 * status.pagesDone / total).coerceIn(0, 100)
        } else {
            binding.progressBarDeterminate.visibility = View.GONE
            binding.progressLabel.text = status.lastLogLine ?: getString(R.string.converting)
        }
    }

    private fun setBusy(busy: Boolean) {
        binding.progressGroup.visibility = if (busy) View.VISIBLE else View.GONE
        if (!busy) binding.progressBarDeterminate.visibility = View.GONE
        binding.convertButton.isEnabled = !busy && chosenUris.isNotEmpty() && Prefs.serverUrl(this).isNotBlank()
        binding.pickFilesButton.isEnabled = !busy
        binding.takePhotoButton.isEnabled = !busy
        binding.settingsButton.isEnabled = !busy
        if (busy) binding.errorText.visibility = View.GONE
    }

    private fun showError(message: String) {
        binding.errorText.text = "$message\n\n${getString(R.string.upload_failed_hint)}"
        binding.errorText.visibility = View.VISIBLE
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }
}
