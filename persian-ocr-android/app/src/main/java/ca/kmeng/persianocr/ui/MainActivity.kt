package ca.kmeng.persianocr.ui

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import android.content.pm.PackageManager
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import ca.kmeng.persianocr.R
import ca.kmeng.persianocr.databinding.ActivityMainBinding
import ca.kmeng.persianocr.net.OcrClient
import ca.kmeng.persianocr.net.OcrOutcome
import ca.kmeng.persianocr.net.Prefs
import ca.kmeng.persianocr.net.ResultHolder
import ca.kmeng.persianocr.net.UploadFile
import ca.kmeng.persianocr.net.uploadFileFrom
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var chosenUris: List<Uri> = emptyList()
    private var pendingCameraUri: Uri? = null

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
        binding.convertButton.isEnabled = chosenUris.isNotEmpty() && Prefs.serverUrl(this).isNotBlank()
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
        val resolver = contentResolver
        val files = chosenUris.mapIndexed { index, uri -> uploadFileFrom(resolver, uri, index + 1) }
        val options = Prefs.options(this)

        lifecycleScope.launch {
            val outcome = withContext(Dispatchers.IO) { OcrClient.convert(baseUrl, files, options) }
            setBusy(false)
            when (outcome) {
                is OcrOutcome.Success -> {
                    ResultHolder.result = outcome.result
                    startActivity(Intent(this@MainActivity, ResultActivity::class.java))
                }
                is OcrOutcome.Failure -> showError(getString(R.string.upload_failed, outcome.reason))
            }
        }
    }

    private fun setBusy(busy: Boolean) {
        binding.progressGroup.visibility = if (busy) View.VISIBLE else View.GONE
        binding.convertButton.isEnabled = !busy && chosenUris.isNotEmpty()
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
