package ca.kmeng.persianocr.ui

import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import ca.kmeng.persianocr.R
import ca.kmeng.persianocr.databinding.ActivitySettingsBinding
import ca.kmeng.persianocr.net.ConnectionCheck
import ca.kmeng.persianocr.net.OcrClient
import ca.kmeng.persianocr.net.OcrOptions
import ca.kmeng.persianocr.net.Prefs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        binding.serverUrlInput.setText(Prefs.serverUrl(this))
        val options = Prefs.options(this)
        binding.verifySwitch.isChecked = options.verify
        binding.normalizeSwitch.isChecked = options.normalize
        binding.pageNumbersSwitch.isChecked = options.pageNumbers
        when (options.passes) {
            1 -> binding.passes1.isChecked = true
            3 -> binding.passes3.isChecked = true
            else -> binding.passes2.isChecked = true
        }

        binding.testConnectionButton.setOnClickListener { testConnection() }
        binding.saveSettingsButton.setOnClickListener { saveAndFinish() }
    }

    private fun selectedPasses(): Int = when (binding.passesGroup.checkedRadioButtonId) {
        binding.passes1.id -> 1
        binding.passes3.id -> 3
        else -> 2
    }

    private fun testConnection() {
        val baseUrl = OcrClient.normalizeBaseUrl(binding.serverUrlInput.text?.toString().orEmpty())
        if (baseUrl == null) {
            showConnectionResult(getString(R.string.no_server_set), success = false)
            return
        }
        binding.testProgress.visibility = View.VISIBLE
        binding.testConnectionButton.isEnabled = false
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) { OcrClient.testConnection(baseUrl) }
            binding.testProgress.visibility = View.GONE
            binding.testConnectionButton.isEnabled = true
            when (result) {
                is ConnectionCheck.Ok -> showConnectionResult(
                    getString(R.string.connection_ok, result.detail), success = true
                )
                is ConnectionCheck.Failed -> showConnectionResult(
                    getString(R.string.connection_failed, result.reason), success = false
                )
            }
        }
    }

    private fun showConnectionResult(message: String, success: Boolean) {
        binding.connectionResultText.text = message
        binding.connectionResultText.setTextColor(
            resources.getColor(if (success) R.color.ok else R.color.warn, theme)
        )
        binding.connectionResultText.visibility = View.VISIBLE
    }

    private fun saveAndFinish() {
        val normalized = OcrClient.normalizeBaseUrl(binding.serverUrlInput.text?.toString().orEmpty()) ?: ""
        Prefs.setServerUrl(this, normalized)
        Prefs.setOptions(
            this,
            OcrOptions(
                verify = binding.verifySwitch.isChecked,
                normalize = binding.normalizeSwitch.isChecked,
                pageNumbers = binding.pageNumbersSwitch.isChecked,
                passes = selectedPasses(),
            )
        )
        finish()
    }

    override fun onSupportNavigateUp(): Boolean {
        saveAndFinish()
        return true
    }
}
