<div dir="rtl">

# اپِ Persian OCR (اندروید)

اپِ سبکِ اندرویدی که عکس یا PDF می‌گیرد، آن را به سرورِ `persian-ocr serve`
(همان ابزارِ پایتونیِ کنارِ همین پوشه) می‌فرستد، و متنِ تبدیل‌شده و
وارسی‌شده را نشان می‌دهد. **هیچ کلیدِ API در اپ نیست** — کلید یا اشتراکِ
Claude Code فقط روی سروری که خودتان اجرا می‌کنید لازم است.

## راه‌اندازی

۱. روی یک رایانه (همان که Claude Code یا کلیدِ API دارد):

```bash
cd persian-ocr
pip install -e .
persian-ocr serve --host 0.0.0.0 --port 8765
```

۲. مطمئن شوید گوشی و آن رایانه در یک شبکه‌ی Wi-Fi هستند.

۳. اپ را نصب کنید، در تنظیمات نشانیِ رایانه را وارد کنید (مثلِ
`http://192.168.1.23:8765`)، «آزمایشِ اتصال» را بزنید، بعد عکس یا PDF
انتخاب کنید و «تبدیل به متن» را بزنید.

## نکته‌ی امنیتی

ارتباطِ اپ با سرور رمزنگاری‌شده نیست (HTTP ساده، برای استفاده در شبکه‌ی
خانگیِ قابلِ اعتماد). آن را روی اینترنتِ عمومی در معرضِ دید قرار ندهید.

</div>

---

## Persian OCR — Android app

A thin Android client for `persian-ocr serve` (the Python tool next to this
directory): pick photos or a PDF, upload them to a server you run, get back
verified Persian text. **No API key lives in this app** — the key or Claude
Code login belongs to the server you point it at, never to the phone.

### Setup

1. On a computer with Claude Code (or an API key) installed:

   ```bash
   cd persian-ocr
   pip install -e .
   persian-ocr serve --host 0.0.0.0 --port 8765
   ```

2. Put the phone on the same Wi-Fi network as that computer.
3. Install the app, open Settings, enter the computer's address
   (e.g. `http://192.168.1.23:8765`), tap "Test connection", then pick photos
   or a PDF and tap "Convert to text".

### Why a server at all

The heavy lifting — vision OCR, cross-pass consensus, verification against the
image, vocabulary checks — is Python code that needs `pymupdf`/`Pillow` and
either an Anthropic API key or a signed-in Claude Code CLI. None of that fits
sensibly inside a phone app, and shipping an API key inside an APK would leak
it to anyone who decompiles it. So the app stays a thin, keyless client, and
`persian-ocr serve` (already part of this repo) does the actual conversion.

### Security note

Traffic between the app and the server is plain HTTP (`usesCleartextTraffic`),
intended for a trusted home/office network. Do not expose the server to the
open internet without adding your own TLS and authentication in front of it.

### Building

This is a separate Gradle project (own `settings.gradle.kts`), so it builds
independently of the `PriceWatcher` app in `../app`:

```bash
cd persian-ocr-android
gradle assembleDebug   # or: ./gradlew assembleDebug if you generate a wrapper
```

Building requires network access to `google()` (Google's Maven repo, for the
Android Gradle Plugin and SDK) and an installed Android SDK — the
`.github/workflows/persian-ocr-android.yml` workflow in this repo does both
automatically and uploads the resulting debug APK as a build artifact on every
push that touches this directory.

### Project layout

```
app/src/main/java/ca/kmeng/persianocr/
  net/OcrClient.kt      — multipart upload to /convert, no external HTTP library
  net/Prefs.kt          — server address + options, in SharedPreferences
  net/ResultHolder.kt   — passes the (possibly large) result between activities
  ui/MainActivity.kt    — pick files / take a photo / convert
  ui/SettingsActivity.kt — server address, test connection, OCR options
  ui/ResultActivity.kt  — show the text; copy / share / save as .txt
```
