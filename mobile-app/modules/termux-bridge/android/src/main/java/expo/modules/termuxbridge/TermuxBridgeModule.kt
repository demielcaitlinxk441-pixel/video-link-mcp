package expo.modules.termuxbridge

import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import android.app.Dialog
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.FileProvider
import expo.modules.kotlin.Promise
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.UUID
import org.json.JSONObject

class TermuxBridgeModule : Module() {
  private val desktopUserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
  private var initError: Throwable? = null

  private fun ensureReady() {
    initError?.let { throw Exception("内置下载引擎初始化失败", it) }
    try {
      val context = appContext.reactContext ?: throw Exception("Android context unavailable")
      YoutubeDL.getInstance().init(context)
      FFmpeg.getInstance().init(context)
    } catch (error: Throwable) {
      initError = error
      throw error
    }
  }

  private fun normalizeUrl(url: String): String {
    if (!url.contains("b23.tv", ignoreCase = true)) return url
    return try {
      val connection = (URL(url).openConnection() as HttpURLConnection).apply {
        instanceFollowRedirects = false
        connectTimeout = 10000
        readTimeout = 10000
        setRequestProperty("User-Agent", desktopUserAgent)
      }
      connection.connect()
      val location = connection.getHeaderField("Location") ?: url
      connection.disconnect()
      Regex("/video/(BV[0-9A-Za-z]+)").find(location)?.groupValues?.get(1)?.let {
        "https://www.bilibili.com/video/$it"
      } ?: location
    } catch (_: Throwable) {
      url
    }
  }

  private fun httpJson(url: String, body: String, headers: Map<String, String>): JSONObject {
    val connection = (URL(url).openConnection() as HttpURLConnection).apply {
      requestMethod = "POST"
      doOutput = true
      connectTimeout = 30000
      readTimeout = 30000
      headers.forEach { (key, value) -> setRequestProperty(key, value) }
    }
    connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
    val status = connection.responseCode
    val stream = if (status in 200..299) connection.inputStream else connection.errorStream
    val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
    connection.disconnect()
    if (status !in 200..299) throw Exception("接口请求失败（HTTP $status）：${response.take(240)}")
    return JSONObject(response)
  }

  private fun wechatChannelsDownload(shareUrl: String, cookie: String, outputDir: String): String {
    val parse = httpJson(
      "https://yuanbao.tencent.com/api/weixin/get_parse_result",
      JSONObject().apply { put("type", "video_channel_url"); put("url", shareUrl); put("scene", 1) }.toString(),
      mapOf("Content-Type" to "application/json", "Accept" to "application/json, text/plain, */*", "Accept-Language" to "zh-CN,zh;q=0.9,en;q=0.8", "Origin" to "https://yuanbao.tencent.com", "Referer" to "https://yuanbao.tencent.com/", "Cookie" to cookie, "User-Agent" to desktopUserAgent, "X-Requested-With" to "XMLHttpRequest", "X-Source" to "web", "X-Web-Third-Source" to "main"),
    )
    val parsed = parse.optJSONObject("data") ?: throw Exception("元宝没有返回视频号授权结果")
    val exportId = parsed.optString("wx_export_id")
    val playable = parsed.optString("playable_url")
    val playableParams = android.net.Uri.parse(playable)
    val token = playableParams.getQueryParameter("token") ?: ""
    val eid = playableParams.getQueryParameter("eid").takeUnless { it.isNullOrBlank() } ?: exportId
    if (eid.isBlank()) throw Exception("没有找到视频号内容标识")
    val rid = "${System.currentTimeMillis().toString(16)}-${UUID.randomUUID().toString().take(8)}"
    val feedUrl = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info?_rid=$rid&_pageUrl=https:%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed"
    val feedReferer = "https://channels.weixin.qq.com/finder-preview/pages/feed?entry_card_type=48&comment_scene=39&appid=0&token=${URLEncoder.encode(token, "UTF-8")}&entry_scene=0&eid=${URLEncoder.encode(eid, "UTF-8")}"
    val feed = httpJson(feedUrl, JSONObject().apply { put("baseReq", JSONObject().put("generalToken", token)); put("exportId", eid) }.toString(), mapOf("Content-Type" to "application/json", "Accept" to "application/json, text/plain, */*", "Accept-Language" to "zh-CN,zh;q=0.9,en;q=0.8", "Origin" to "https://channels.weixin.qq.com", "Referer" to feedReferer, "User-Agent" to desktopUserAgent, "X-Requested-With" to "XMLHttpRequest"))
    val data = feed.optJSONObject("data") ?: throw Exception("微信视频号接口没有返回视频信息")
    val feedInfo = data.optJSONObject("feedInfo") ?: throw Exception("视频号内容为空")
    val videoUrl = feedInfo.optString("videoUrl").ifBlank { feedInfo.optJSONObject("h264VideoInfo")?.optString("videoUrl") ?: feedInfo.optJSONObject("h265VideoInfo")?.optString("videoUrl") ?: "" }
    if (videoUrl.isBlank()) throw Exception("没有找到视频文件地址")
    val title = feedInfo.optString("description").lineSequence().firstOrNull()?.trim().orEmpty().ifBlank { "wechat_channels_video" }.replace(Regex("[<>:\"/\\\\|?*\\r\\n#]"), " ").trim().take(80)
    val directory = File(outputDir).apply { mkdirs() }
    val target = File(directory, "$title-${System.currentTimeMillis()}.mp4")
    val download = (URL(videoUrl).openConnection() as HttpURLConnection).apply { connectTimeout = 30000; readTimeout = 120000; setRequestProperty("Referer", "https://channels.weixin.qq.com/"); setRequestProperty("User-Agent", desktopUserAgent) }
    download.inputStream.use { input -> target.outputStream().use { output -> input.copyTo(output, 65536) } }
    download.disconnect()
    return target.absolutePath
  }

  override fun definition() = ModuleDefinition {
    Name("TermuxBridge")
    Events("downloadProgress")

    AsyncFunction("isInstalled") {
      ensureReady()
      true
    }

    AsyncFunction("openTermux") { true }

    AsyncFunction("authorizeYuanbao") { promise: Promise ->
      Handler(Looper.getMainLooper()).post {
        val activity = appContext.currentActivity
        if (activity == null || activity.isFinishing || activity.isDestroyed) {
          promise.reject("NO_ACTIVITY", "当前页面不可用，无法打开授权窗口", null)
          return@post
        }
        try {
          CookieManager.getInstance().setAcceptCookie(true)
          val density = activity.resources.displayMetrics.density
          fun dp(value: Int) = (value * density).toInt()
          val webView = WebView(activity).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.userAgentString = desktopUserAgent
            webViewClient = WebViewClient()
            webChromeClient = WebChromeClient()
            setBackgroundColor(Color.WHITE)
          }
          val title = TextView(activity).apply {
            text = "元宝授权"
            textSize = 22f
            setTextColor(Color.rgb(20, 42, 67))
            setPadding(dp(20), dp(18), dp(20), dp(4))
          }
          val hint = TextView(activity).apply {
            text = "请在网页中登录元宝，完成后点击底部“完成登录”。"
            textSize = 14f
            setTextColor(Color.rgb(98, 125, 152))
            setPadding(dp(20), 0, dp(20), dp(12))
          }
          val cancel = Button(activity).apply { text = "取消" }
          val finish = Button(activity).apply { text = "完成登录" }
          val actions = LinearLayout(activity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.END or Gravity.CENTER_VERTICAL
            setPadding(dp(8), dp(4), dp(8), dp(8))
            addView(cancel, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(52)))
            addView(finish, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(52)))
          }
          val content = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            addView(title, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            addView(hint, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            addView(webView, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
            addView(actions, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
          }
          val dialog = Dialog(activity)
          var settled = false
          dialog.setContentView(content)
          dialog.setCancelable(true)
          cancel.setOnClickListener { dialog.cancel() }
          finish.setOnClickListener {
            if (settled) return@setOnClickListener
            val cookie = CookieManager.getInstance().getCookie("https://yuanbao.tencent.com/").orEmpty()
            if (cookie.isBlank()) {
              promise.reject("NO_COOKIE", "未检测到元宝登录状态", null)
            } else {
              settled = true
              CookieManager.getInstance().flush()
              promise.resolve(cookie)
            }
            dialog.dismiss()
          }
          dialog.setOnCancelListener { if (!settled) { settled = true; promise.reject("CANCELLED", "授权已取消", null) } }
          dialog.setOnDismissListener { (webView.parent as? ViewGroup)?.removeView(webView); webView.destroy() }
          dialog.show()
          dialog.window?.setBackgroundDrawable(ColorDrawable(Color.WHITE))
          dialog.window?.setLayout(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT)
          webView.loadUrl("https://yuanbao.tencent.com/")
        } catch (error: Throwable) {
          promise.reject("AUTH_UI_FAILED", "无法打开元宝授权窗口", error)
        }
      }
    }

    AsyncFunction("runWechatChannels") { url: String, cookie: String, outputDir: String? ->
      if (cookie.isBlank()) throw Exception("请先完成元宝授权")
      wechatChannelsDownload(url, cookie, outputDir?.takeIf { it.isNotBlank() } ?: "/sdcard/Download/VideoLink")
    }

    AsyncFunction("deleteFile") { path: String ->
      val rawPath = path.removePrefix("file://")
      val file = File(android.net.Uri.decode(rawPath))
      if (!file.exists()) true else if (file.isFile && file.delete()) true else throw Exception("文件无法删除：${file.name}")
    }

    AsyncFunction("openVideo") { path: String, promise: Promise ->
      Handler(Looper.getMainLooper()).post {
        try {
          val activity = appContext.currentActivity ?: throw Exception("当前页面不可用")
          val file = File(android.net.Uri.decode(path.removePrefix("file://")))
          if (!file.exists()) throw Exception("视频文件不存在")
          val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.SharingFileProvider", file)
          val viewIntent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "video/*")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
          }
          val sendIntent = Intent(Intent.ACTION_SEND).apply {
            type = "video/*"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
          }
          if (viewIntent.resolveActivity(activity.packageManager) == null && sendIntent.resolveActivity(activity.packageManager) == null) {
            promise.resolve(false)
          } else {
            val chooser = Intent.createChooser(sendIntent, "打开或发送视频").apply {
              putExtra(Intent.EXTRA_INITIAL_INTENTS, arrayOf(viewIntent))
            }
            activity.startActivity(chooser)
            promise.resolve(true)
          }
        } catch (error: Throwable) {
          promise.resolve(false)
        }
      }
    }

    AsyncFunction("shareVideoToWechat") { path: String, promise: Promise ->
      Handler(Looper.getMainLooper()).post {
        try {
          val activity = appContext.currentActivity ?: throw Exception("当前页面不可用")
          val file = File(android.net.Uri.decode(path.removePrefix("file://")))
          if (!file.exists()) throw Exception("视频文件不存在")
          val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.SharingFileProvider", file)
          val intent = Intent(Intent.ACTION_SEND).apply {
            type = "video/*"
            putExtra(Intent.EXTRA_STREAM, uri)
            setPackage("com.tencent.mm")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
          }
          if (intent.resolveActivity(activity.packageManager) == null) {
            promise.resolve(false)
          } else {
            activity.startActivity(intent)
            promise.resolve(true)
          }
        } catch (_: Throwable) {
          promise.resolve(false)
        }
      }
    }

    AsyncFunction("cancelYtDlp") { downloadId: String ->
      ensureReady()
      YoutubeDL.getInstance().destroyProcessById(downloadId)
    }

    AsyncFunction("runYtDlp") { url: String, outputDir: String?, downloadId: String? ->
      ensureReady()
      val output = outputDir?.takeIf { it.isNotBlank() } ?: "/sdcard/Download/VideoLink"
      val processId = downloadId?.takeIf { it.isNotBlank() } ?: UUID.randomUUID().toString()
      File(output).mkdirs()
      val request = YoutubeDLRequest(normalizeUrl(url)).apply {
        addOption("--no-update")
        addOption("--no-playlist")
        addOption("--add-header", "Referer:https://www.bilibili.com/")
        addOption("--add-header", "User-Agent:$desktopUserAgent")
        addOption("-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best")
        addOption("--merge-output-format", "mp4")
        addOption("-P", output)
        addOption("-o", "%(title)s.%(ext)s")
      }
      YoutubeDL.getInstance().execute(request, processId, false) { progress, _, _ ->
        sendEvent("downloadProgress", mapOf("id" to processId, "progress" to progress.toDouble()))
        kotlin.Unit
      }
      val savedFile = File(output).listFiles()
        ?.filter { it.isFile && !it.name.endsWith(".part") }
        ?.maxByOrNull { it.lastModified() }
        ?: throw Exception("下载完成但没有找到视频文件")
      savedFile.absolutePath
    }
  }
}
