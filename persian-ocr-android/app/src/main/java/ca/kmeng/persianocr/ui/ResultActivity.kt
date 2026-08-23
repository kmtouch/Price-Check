package ca.kmeng.persianocr.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import ca.kmeng.persianocr.R
import ca.kmeng.persianocr.databinding.ActivityResultBinding
import ca.kmeng.persianocr.net.OcrResult
import ca.kmeng.persianocr.net.ResultHolder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class ResultActivity : AppCompatActivity() {

    private lateinit var binding: ActivityResultBinding
    private var result: OcrResult? = null

    private val createDocument = registerForActivityResult(
        ActivityResultContracts.CreateDocument("text/plain")
    ) { uri -> if (uri != null) writeTo(uri) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityResultBinding.inflate(layoutInflater)
        setContentView(binding.root)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        val current = ResultHolder.result
        if (current == null) {
            finish()
            return
        }
        result = current
        render(current)

        binding.copyButton.setOnClickListener { copyToClipboard(current.text) }
        binding.shareButton.setOnClickListener { share(current.text) }
        binding.saveButton.setOnClickListener {
            createDocument.launch(defaultFileName())
        }
    }

    private fun render(result: OcrResult) {
        binding.confidenceText.text = getString(R.string.confidence_label, result.confidencePercent)
        val stats = StringBuilder(getString(R.string.words_pages_label, result.words, result.pages))
        if (result.corrections > 0) {
            stats.append(" · ").append(getString(R.string.corrections_label, result.corrections))
        }
        binding.statsText.text = stats
        if (result.lowConfidencePages.isNotEmpty()) {
            binding.lowConfidenceText.text = getString(
                R.string.low_confidence_label,
                result.lowConfidencePages.joinToString("، ")
            )
            binding.lowConfidenceText.visibility = View.VISIBLE
        } else {
            binding.lowConfidenceText.visibility = View.GONE
        }
        binding.resultTextView.text = result.text
    }

    private fun copyToClipboard(text: String) {
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText(getString(R.string.app_name), text))
        Toast.makeText(this, getString(R.string.copied), Toast.LENGTH_SHORT).show()
    }

    private fun share(text: String) {
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, text)
        }
        startActivity(Intent.createChooser(intent, getString(R.string.share)))
    }

    private fun writeTo(uri: Uri) {
        val text = result?.text ?: return
        runCatching {
            contentResolver.openOutputStream(uri)?.use { stream ->
                stream.write(text.toByteArray(Charsets.UTF_8))
            } ?: error("could not open the destination for writing")
        }.onSuccess {
            Toast.makeText(this, getString(R.string.saved), Toast.LENGTH_SHORT).show()
        }.onFailure { e ->
            Toast.makeText(this, getString(R.string.save_failed, e.message), Toast.LENGTH_LONG).show()
        }
    }

    private fun defaultFileName(): String {
        val stamp = SimpleDateFormat("yyyy-MM-dd-HHmm", Locale.US).format(Date())
        return "persian-ocr-$stamp.txt"
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }
}
