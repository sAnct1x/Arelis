package app.arelis

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class ScanActivity : ComponentActivity() {
    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private val scanner = BarcodeScanning.getClient(
        BarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
            .build(),
    )
    private val handled = AtomicBoolean(false)
    private val status = mutableStateOf("Point at Settings → Notify on the PC.")

    private val askCamera = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) bindCamera() else {
            status.value = "Camera is needed to scan. You can paste the pairing text instead."
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            val message by status
            ArelisTheme {
                Box(Modifier.fillMaxSize().background(Campfire.bg0)) {
                    AndroidView(
                        modifier = Modifier.fillMaxSize(),
                        factory = { ctx ->
                            PreviewView(ctx).also { preview ->
                                preview.implementationMode = PreviewView.ImplementationMode.COMPATIBLE
                                preview.tag = "preview"
                                this@ScanActivity.previewView = preview
                                maybeStartCamera()
                            }
                        },
                    )
                    Canvas(Modifier.fillMaxSize()) {
                        val side = size.minDimension * 0.62f
                        val left = (size.width - side) / 2f
                        val top = (size.height - side) / 2f
                        val scrim = Color(0x99160D07)
                        drawRect(scrim, Offset(0f, 0f), Size(size.width, top))
                        drawRect(
                            scrim,
                            Offset(0f, top + side),
                            Size(size.width, size.height - top - side),
                        )
                        drawRect(scrim, Offset(0f, top), Size(left, side))
                        drawRect(
                            scrim,
                            Offset(left + side, top),
                            Size(size.width - left - side, side),
                        )
                        val len = side * 0.16f
                        val c = Color(0xFFFF7A22)
                        val stroke = 7f
                        fun corner(x: Float, y: Float, dx: Float, dy: Float) {
                            drawLine(c, Offset(x, y), Offset(x + dx * len, y), strokeWidth = stroke, cap = StrokeCap.Round)
                            drawLine(c, Offset(x, y), Offset(x, y + dy * len), strokeWidth = stroke, cap = StrokeCap.Round)
                        }
                        corner(left, top, 1f, 1f)
                        corner(left + side, top, -1f, 1f)
                        corner(left, top + side, 1f, -1f)
                        corner(left + side, top + side, -1f, -1f)
                    }
                    GhostLink(
                        "← back",
                        onClick = { finish() },
                        modifier = Modifier
                            .align(Alignment.TopStart)
                            .statusBarsPadding()
                            .padding(18.dp),
                    )
                    Text(
                        text = message,
                        color = Campfire.accent2,
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .fillMaxWidth()
                            .navigationBarsPadding()
                            .padding(24.dp),
                    )
                }
            }
        }
    }

    private var previewView: PreviewView? = null

    private fun maybeStartCamera() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            bindCamera()
        } else {
            askCamera.launch(Manifest.permission.CAMERA)
        }
    }

    private fun bindCamera() {
        val previewView = previewView ?: return
        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener({
            val provider = providerFuture.get()
            val preview = Preview.Builder().build().also {
                it.setSurfaceProvider(previewView.surfaceProvider)
            }
            val analysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                .build()
            analysis.setAnalyzer(cameraExecutor) { imageProxy ->
                val media = imageProxy.image
                if (media == null) {
                    imageProxy.close()
                    return@setAnalyzer
                }
                val image = InputImage.fromMediaImage(media, imageProxy.imageInfo.rotationDegrees)
                scanner.process(image)
                    .addOnSuccessListener { barcodes ->
                        val text = barcodes.firstOrNull { !it.rawValue.isNullOrBlank() }?.rawValue
                        if (!text.isNullOrBlank()) onCode(text)
                    }
                    .addOnFailureListener {
                        status.value = "Camera is up. If nothing locks, go back and paste."
                    }
                    .addOnCompleteListener { imageProxy.close() }
            }
            provider.unbindAll()
            provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
        }, ContextCompat.getMainExecutor(this))
    }

    private fun onCode(text: String) {
        if (!handled.compareAndSet(false, true)) return
        setResult(RESULT_OK, android.content.Intent().putExtra(EXTRA_PAYLOAD, text))
        finish()
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraExecutor.shutdown()
        scanner.close()
    }

    companion object {
        const val EXTRA_PAYLOAD = "payload"
    }
}
