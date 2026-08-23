package ca.kmeng.persianocr.net

/**
 * Holds the most recent conversion result in memory for [ResultActivity][ca.kmeng.persianocr.ui.ResultActivity]
 * to read. A converted document can be large, so it is passed this way rather
 * than through an Intent extra, which is capped by the Binder transaction size.
 */
object ResultHolder {
    var result: OcrResult? = null
}
