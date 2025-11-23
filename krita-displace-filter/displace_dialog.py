from krita import *
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QComboBox, QPushButton,
    QCheckBox, QGroupBox, QMessageBox, QSlider
)
from PyQt5.QtCore import Qt, QTimer, QSettings
from PyQt5.QtGui import QImage, QPixmap, QColor
import struct
import time

import time
import math
import struct

from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QCheckBox, QSlider, QDoubleSpinBox, QWidget
)
from PyQt5.QtCore import Qt, QSettings, QTimer
from PyQt5.QtGui import QImage, QPixmap

class DisplaceDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Displace Map Filter")
        self.setMinimumWidth(700)

        self.doc = None

        # Full resolution QImages (8-bit sRGB, created once)
        self.src_qimage_full = None
        self.disp_qimage_full = None

        # Caching for scaled (preview size) data
        self.cached_src_scaled_data = None
        self.cached_disp_scaled_data = None
        self.cached_preview_scale = 0.0
        self.cached_w = 0
        self.cached_h = 0

        # Settings persistence
        self.settings = QSettings("Krita", "DisplaceMapFilter")

        # default preview scale (fraction of original)
        self.preview_scale = 0.25
        self.preview_enabled = False

        # Main horizontal layout: Preview | Settings
        main_layout = QHBoxLayout(self)

        # === LEFT SIDE: Preview ===
        preview_container = QVBoxLayout()

        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout()

        # Preview enable checkbox
        self.preview_enable_check = QCheckBox("Enable Preview (may be slow)")
        self.preview_enable_check.setChecked(False)
        self.preview_enable_check.stateChanged.connect(self.on_preview_enable_changed)
        preview_layout.addWidget(self.preview_enable_check)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(400, 400)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setText("Preview disabled.\nEnable checkbox above to see preview.")
        preview_layout.addWidget(self.preview_label)

        # preview scale slider (5% .. 100%)
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("Scale:"))
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(5, 100)
        self.scale_slider.setValue(int(self.preview_scale * 100))
        self.scale_slider.valueChanged.connect(self.on_preview_scale_changed)
        self.scale_label = QLabel(f"{int(self.preview_scale * 100)}%")
        slider_layout.addWidget(self.scale_slider)
        slider_layout.addWidget(self.scale_label)
        preview_layout.addLayout(slider_layout)

        preview_group.setLayout(preview_layout)
        preview_container.addWidget(preview_group)
        preview_container.addStretch()

        main_layout.addLayout(preview_container)

        # === RIGHT SIDE: Settings ===
        settings_container = QVBoxLayout()

        # --- Layer selection ---
        layer_group = QGroupBox("Displacement Map Layer")
        layer_layout = QVBoxLayout()

        self.layer_combo = QComboBox()
        self.populate_layers()
        self.layer_combo.currentIndexChanged.connect(self.on_layer_changed)
        layer_layout.addWidget(self.layer_combo)

        refresh_btn = QPushButton("Refresh Layer List")
        refresh_btn.clicked.connect(self.populate_layers)
        layer_layout.addWidget(refresh_btn)

        layer_group.setLayout(layer_layout)
        settings_container.addWidget(layer_group)

        # --- Settings ---
        settings_group = QGroupBox("Displacement Settings")
        settings_layout = QVBoxLayout()

        # Strength
        s_layout = QHBoxLayout()
        s_layout.addWidget(QLabel("Strength:"))
        self.strength_spin = QDoubleSpinBox()
        self.strength_spin.setRange(0.0, 5000.0)
        self.strength_spin.setValue(100.0)
        self.strength_spin.setSingleStep(1.0)
        self.strength_spin.valueChanged.connect(self.schedule_preview_update)
        s_layout.addWidget(self.strength_spin)
        settings_layout.addLayout(s_layout)

        # Channel
        ch_layout = QHBoxLayout()
        ch_layout.addWidget(QLabel("Channel:"))
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Red", "Green", "Blue", "Luminosity"])
        self.channel_combo.currentIndexChanged.connect(self.schedule_preview_update)
        ch_layout.addWidget(self.channel_combo)
        settings_layout.addLayout(ch_layout)

        # Direction
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Direction:"))
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["Horizontal", "Vertical", "Both"])
        self.direction_combo.currentIndexChanged.connect(self.schedule_preview_update)
        dir_layout.addWidget(self.direction_combo)
        settings_layout.addLayout(dir_layout)

        # Wrap
        wrap_layout = QHBoxLayout()
        wrap_layout.addWidget(QLabel("Edge Handling:"))
        self.wrap_combo = QComboBox()
        self.wrap_combo.addItems(["Transparent", "Wrap", "Clamp"])
        self.wrap_combo.currentIndexChanged.connect(self.schedule_preview_update)
        wrap_layout.addWidget(self.wrap_combo)
        settings_layout.addLayout(wrap_layout)

        settings_group.setLayout(settings_layout)
        settings_container.addWidget(settings_group)

        # --- Advanced ---
        advanced_group = QGroupBox("Advanced Options")
        advanced_layout = QVBoxLayout()

        self.invert_check = QCheckBox("Invert Displacement")
        self.invert_check.stateChanged.connect(self.schedule_preview_update)
        advanced_layout.addWidget(self.invert_check)

        self.center_check = QCheckBox("Center Displacement (0.5 = no displacement)")
        self.center_check.setChecked(True)
        self.center_check.stateChanged.connect(self.schedule_preview_update)
        advanced_layout.addWidget(self.center_check)

        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("Scale:"))
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.01, 10.0)
        self.scale_spin.setValue(1.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.valueChanged.connect(self.schedule_preview_update)
        scale_layout.addWidget(self.scale_spin)
        advanced_layout.addLayout(scale_layout)

        advanced_group.setLayout(advanced_layout)
        settings_container.addWidget(advanced_group)

        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout()

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("New Layer Name:"))
        self.name_edit = QComboBox()
        self.name_edit.setEditable(True)
        self.name_edit.addItems(["{layer}_displaced", "{layer}_displace", "Displaced"])
        name_layout.addWidget(self.name_edit)
        output_layout.addLayout(name_layout)

        self.create_above_check = QCheckBox("Create above active layer")
        self.create_above_check.setChecked(True)
        output_layout.addWidget(self.create_above_check)

        output_group.setLayout(output_layout)
        settings_container.addWidget(output_group)

        settings_container.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(apply_btn)
        btn_layout.addWidget(cancel_btn)
        settings_container.addLayout(btn_layout)

        main_layout.addLayout(settings_container)

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.render_preview)

        # Throttle timer to limit preview update frequency
        self.last_preview_time = 0
        self.preview_throttle_ms = 200

        self.load_settings()

        try:
            self.load_full_resolution_sources()
        except Exception:
            pass



    def load_settings(self):
        """Load previously saved settings."""
        self.strength_spin.setValue(self.settings.value("strength", 100.0, type=float))
        self.channel_combo.setCurrentIndex(self.settings.value("channel", 0, type=int))
        self.direction_combo.setCurrentIndex(self.settings.value("direction", 0, type=int))
        self.wrap_combo.setCurrentIndex(self.settings.value("wrap_mode", 0, type=int))
        self.invert_check.setChecked(self.settings.value("invert", False, type=bool))
        self.center_check.setChecked(self.settings.value("center", True, type=bool))
        self.scale_spin.setValue(self.settings.value("scale", 1.0, type=float))
        self.preview_scale = self.settings.value("preview_scale", 0.25, type=float)
        self.scale_slider.setValue(int(self.preview_scale * 100))
        self.preview_enabled = self.settings.value("preview_enabled", False, type=bool)
        self.preview_enable_check.setChecked(self.preview_enabled)

        layer_name = self.settings.value("layer_name", "{layer}_displaced", type=str)
        idx = self.name_edit.findText(layer_name)
        if idx >= 0:
            self.name_edit.setCurrentIndex(idx)
        else:
            self.name_edit.setEditText(layer_name)

        self.create_above_check.setChecked(self.settings.value("create_above", True, type=bool))

    def save_settings(self):
        """Save current settings for next time."""
        self.settings.setValue("strength", self.strength_spin.value())
        self.settings.setValue("channel", self.channel_combo.currentIndex())
        self.settings.setValue("direction", self.direction_combo.currentIndex())
        self.settings.setValue("wrap_mode", self.wrap_combo.currentIndex())
        self.settings.setValue("invert", self.invert_check.isChecked())
        self.settings.setValue("center", self.center_check.isChecked())
        self.settings.setValue("scale", self.scale_spin.value())
        self.settings.setValue("preview_scale", self.preview_scale)
        self.settings.setValue("preview_enabled", self.preview_enabled)
        self.settings.setValue("layer_name", self.name_edit.currentText())
        self.settings.setValue("create_above", self.create_above_check.isChecked())

    def accept(self):
        """Override accept to save settings before closing."""
        self.save_settings()
        super().accept()

    def reject(self):
        """Override reject to save settings before closing."""
        self.save_settings()
        super().reject()

    # -------------------- Helpers and Layer Logic --------------------

    def on_layer_changed(self):
        """Handle layer change: invalidate full-res cache and schedule update."""
        self.src_qimage_full = None
        self.disp_qimage_full = None
        self.cached_src_scaled_data = None
        self.cached_disp_scaled_data = None
        self.cached_preview_scale = 0.0
        self.schedule_preview_update(immediate=True)

    def populate_layers(self):
        self.layer_combo.clear()
        doc = Krita.instance().activeDocument()
        if not doc:
            return
        self.doc = doc
        layers = self.collect_layers(doc.rootNode())
        for name in layers:
            self.layer_combo.addItem(name)

        self.on_layer_changed()

    def collect_layers(self, node, out=None):
        if out is None:
            out = []
        if node.type() == 'paintlayer':
            out.append(node.name())
        for c in node.childNodes():
            self.collect_layers(c, out)
        return out

    def on_preview_enable_changed(self, state):
        """Handle preview enable/disable."""
        self.preview_enabled = state == Qt.Checked
        if self.preview_enabled:
            self.preview_label.clear()
            self.schedule_preview_update(immediate=True)
        else:
            self.preview_label.setText("Preview disabled.\nEnable checkbox above to see preview.")
            self.preview_timer.stop()

    def on_preview_scale_changed(self, v):
        self.preview_scale = max(0.01, v / 100.0)
        self.scale_label.setText(f"{v}%")

        # --- Оптимизация: Сброс кэша при изменении масштаба ---
        self.cached_src_scaled_data = None
        self.cached_disp_scaled_data = None
        self.cached_preview_scale = 0.0
        # -----------------------------------------------------

        if self.preview_enabled:
            self.schedule_preview_update(immediate=True)

    def schedule_preview_update(self, immediate=False):
        if not self.preview_enabled:
            return

        current_time = time.time() * 1000
        time_since_last = current_time - self.last_preview_time

        if immediate:
            self.preview_timer.stop()
            self.render_preview()
        else:
            if time_since_last < self.preview_throttle_ms:
                delay = max(50, int(self.preview_throttle_ms - time_since_last))
                self.preview_timer.start(delay)
            else:
                self.preview_timer.start(50)

    # -------------------- Color Conversion Helpers (sRGB <-> Linear) --------------------

    @staticmethod
    def _srgb_to_linear(val_norm):
        """Applies sRGB EOTF (gamma removal) to get LINEAR value."""
        if val_norm <= 0.04045:
            return val_norm / 12.92
        else:
            return math.pow((val_norm + 0.055) / 1.055, 2.4)

    @staticmethod
    def _linear_to_srgb(val_norm):
        """Applies sRGB OETF (gamma correction) for correct visual display."""
        if val_norm <= 0.0031308:
            return 12.92 * val_norm
        else:
            # Оптимизация: использование math.pow
            return 1.055 * math.pow(val_norm, 1.0 / 2.4) - 0.055

    @staticmethod
    def _convert_raw_to_float32(raw_bytes, w, h, bpc, color_depth):
        """
        Converts raw pixel data of any bit depth to a flat list of 32-bit
        LINEAR floats (0.0 - 1.0). Handles sRGB->Linear for 8-bit data.
        """
        float_data = [0.0] * (w * h * 4)
        num_pixels = w * h * 4

        # U8 (Assumed sRGB)
        if bpc == 1:
            for i in range(num_pixels):
                dn = raw_bytes[i] / 255.0
                # CRITICAL: Convert sRGB (gamma) to LINEAR
                float_data[i] = DisplaceDialog._srgb_to_linear(dn)

        # F16/U16 (Assumed LINEAR)
        elif bpc == 2:
            if "F16" in color_depth:
                # Optimized F16 conversion using struct (assumed little-endian)
                for i in range(num_pixels):
                    half_bytes = raw_bytes[i * 2:i * 2 + 2]
                    half_bits = half_bytes[0] | (half_bytes[1] << 8)

                    # Simple half-float to float conversion (approximate for speed)
                    # For Krita's exact half-float format, native functions are better,
                    # but this standard approximation is used here:
                    s = (half_bits >> 15) & 0x01
                    e = (half_bits >> 10) & 0x1F
                    m = half_bits & 0x3FF

                    if e == 0:
                        f = (2**-14) * (m / 1024.0)
                    elif e == 31:
                        f = 1.0 # Inf/NaN check is skipped for performance
                    else:
                        f = (2**(e - 15)) * (1.0 + m / 1024.0)

                    float_data[i] = f if s == 0 else -f

            else:
                # U16: Scale 0-65535 to 0.0-1.0 (LINEAR)
                for i in range(num_pixels):
                    low = raw_bytes[i * 2]
                    high = raw_bytes[i * 2 + 1]
                    val16 = low | (high << 8)
                    float_data[i] = val16 / 65535.0

        # F32 (Assumed LINEAR)
        elif bpc == 4:
            format_string = '<f'
            for i in range(num_pixels):
                float_bytes = raw_bytes[i * 4:i * 4 + 4]
                # Use struct for fast unpacking
                float_data[i] = struct.unpack(format_string, float_bytes)[0]

        return [max(0.0, min(1.0, val)) for val in float_data]


    def load_full_resolution_sources(self):
        """
        Loads full resolution data, converts to LINEAR float, then converts to
        8-bit sRGB QImage for use as the preview source.
        """
        if self.src_qimage_full is not None and self.disp_qimage_full is not None:
            return

        doc = Krita.instance().activeDocument()
        if not doc:
            raise RuntimeError("No active document")
        node = doc.activeNode()
        disp_node = self.find_layer_by_name(doc.rootNode(), self.layer_combo.currentText())

        if not node or not disp_node:
             raise RuntimeError("Active layer or displacement layer not found.")

        w, h = doc.width(), doc.height()
        color_depth = doc.colorDepth()

        # NOTE: projectionPixelData is a Krita-specific function for getting composite data
        src_raw = node.projectionPixelData(0, 0, w, h)
        disp_raw = disp_node.projectionPixelData(0, 0, w, h)

        if not src_raw or not disp_raw:
            raise RuntimeError("Cannot read pixel data")

        src_bytes = bytes(src_raw)
        disp_bytes = bytes(disp_raw)

        expected_pixels = w * h * 4
        if len(src_bytes) % expected_pixels != 0:
            raise RuntimeError("Unexpected pixel data size")
        bpc = len(src_bytes) // expected_pixels
        if bpc not in (1, 2, 4):
            raise RuntimeError(f"Unsupported bytes-per-channel: {bpc}")


        src_float32_linear = self._convert_raw_to_float32(src_bytes, w, h, bpc, color_depth)
        disp_float32_linear = self._convert_raw_to_float32(disp_bytes, w, h, bpc, color_depth)

        src_8bit = bytearray(w * h * 4)
        disp_8bit = bytearray(w * h * 4)

        for i in range(w * h * 4):
            # Convert LINEAR float to sRGB 8-bit for VISUAL QImage display
            srgb_val_src = self._linear_to_srgb(src_float32_linear[i])
            src_8bit[i] = max(0, min(255, int(srgb_val_src * 255.0)))

            srgb_val_disp = self._linear_to_srgb(disp_float32_linear[i])
            disp_8bit[i] = max(0, min(255, int(srgb_val_disp * 255.0)))


        self.src_qimage_full = QImage(bytes(src_8bit), w, h, w * 4, QImage.Format_ARGB32)
        self.disp_qimage_full = QImage(bytes(disp_8bit), w, h, w * 4, QImage.Format_ARGB32)

        self.cached_src_scaled_data = None
        self.cached_disp_scaled_data = None
        self.cached_preview_scale = 0.0


    def get_scaled_preview_data(self):
        """
        Returns cached scaled bytearray data or creates it if the scale changed.
        The scale check is redundant here because it's reset in on_preview_scale_changed,
        but it remains as a safeguard.
        """

        # Check if cache is valid (scale, data)
        if (self.cached_src_scaled_data and
            self.cached_preview_scale == self.preview_scale and
            self.cached_w > 0):
            return self.cached_src_scaled_data, self.cached_disp_scaled_data, self.cached_w, self.cached_h

        if not self.src_qimage_full or not self.disp_qimage_full:
            self.load_full_resolution_sources()

        w_orig = self.src_qimage_full.width()
        h_orig = self.src_qimage_full.height()

        pw = max(1, int(w_orig * self.preview_scale))
        ph = max(1, int(h_orig * self.preview_scale))

        src_scaled = self.src_qimage_full.scaled(pw, ph, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        disp_scaled = self.disp_qimage_full.scaled(pw, ph, Qt.IgnoreAspectRatio, Qt.FastTransformation)

        # Getting raw bytes from QImage
        src_bits = src_scaled.constBits()
        disp_bits = disp_scaled.constBits()

        src_bits.setsize(pw * ph * 4)
        disp_bits.setsize(pw * ph * 4)

        self.cached_src_scaled_data = bytearray(src_bits)
        self.cached_disp_scaled_data = bytearray(disp_bits)
        self.cached_preview_scale = self.preview_scale
        self.cached_w = pw
        self.cached_h = ph

        return self.cached_src_scaled_data, self.cached_disp_scaled_data, pw, ph

    def render_preview(self):
        if not self.preview_enabled:
            return

        self.last_preview_time = time.time() * 1000

        try:
            src_data, disp_data, pw, ph = self.get_scaled_preview_data()
        except Exception as e:
            self.preview_label.setText(f"Preview error: {str(e)}")
            print("Preview load error:", e)
            return

        if not src_data or not disp_data:
            self.preview_label.clear()
            return

        settings = self.get_settings()

        strength = settings['strength'] * settings['scale'] * self.preview_scale
        channel_idx = settings['channel']
        direction = settings['direction']
        wrap_mode = settings['wrap_mode']
        center = settings['center']
        invert = settings['invert']

        MAX_VAL = 255.0
        if center:
            # Optimized: (d_val / 255.0 - 0.5) * 2.0 = d_val * (2.0/255.0) - 1.0
            NORM_CENTER_MULT = 2.0 / MAX_VAL
            NORM_CENTER_OFFSET = 1.0
        else:
            # Optimized: d_val / 255.0 = d_val * (1.0/255.0)
            NORM_CENTER_MULT = 1.0 / MAX_VAL
            NORM_CENTER_OFFSET = 0.0

        # Инверсия (применяется в конце)
        INV_SIGN = -1.0 if invert else 1.0

        out_data = bytearray(pw * ph * 4) # Output buffer (initialized to zeros/transparent)

        # Оптимизация: Используем локальные переменные для часто вызываемых функций/констант
        # (уже сделано для переменных, но можно для range/len)
        pw_4 = pw * 4

        for y in range(ph):
            row_base = y * pw_4
            for x in range(pw):
                idx = row_base + x * 4

                # Read displacement value (BGRA format, 8-bit sRGB)
                b = disp_data[idx]
                g = disp_data[idx + 1]
                r = disp_data[idx + 2]

                # Extract channel value (Inlined logic for speed)
                if channel_idx == 3:  # Luminosity
                    # Constant weights are floats
                    d_val = 0.299 * r + 0.587 * g + 0.114 * b
                elif channel_idx == 0:  # Red
                    d_val = float(r)
                elif channel_idx == 1:  # Green
                    d_val = float(g)
                else:  # Blue
                    d_val = float(b)

                # Normalize displacement (Range 0..1 or -1..1) (Inlined logic for speed)
                dn = (d_val * NORM_CENTER_MULT) - NORM_CENTER_OFFSET if center else d_val * NORM_CENTER_MULT

                # Apply inversion and strength
                disp_px = dn * INV_SIGN * strength

                # Apply displacement direction (Inlined logic for speed)
                if direction == 0:  # Horizontal
                    sx, sy = x + disp_px, y
                elif direction == 1:  # Vertical
                    sx, sy = x, y + disp_px
                else:  # Both
                    sx, sy = x + disp_px, y + disp_px

                # Apply wrap mode (Inlined logic for speed)
                sx_i = int(round(sx))
                sy_i = int(round(sy))

                if wrap_mode == 1:  # Wrap
                    sx_i %= pw
                    sy_i %= ph
                elif wrap_mode == 2:  # Clamp
                    sx_i = max(0, min(pw - 1, sx_i))
                    sy_i = max(0, min(ph - 1, sy_i))

                if 0 <= sx_i < pw and 0 <= sy_i < ph:
                    src_idx = (sy_i * pw + sx_i) * 4
                    out_data[idx:idx+4] = src_data[src_idx:src_idx+4]
                else:
                    # Transparent is already set because out_data is initialized to 0
                    pass

        out_image = QImage(bytes(out_data), pw, ph, pw * 4, QImage.Format_ARGB32)

        # Use SmoothTransformation for final scaling to fit the QLabel size
        self.preview_label.setPixmap(QPixmap.fromImage(out_image).scaled(
            self.preview_label.width(), self.preview_label.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))

    # -------------------- Utilities --------------------
    def get_settings(self):
        return {
            'displacement_layer': self.layer_combo.currentText(),
            'strength': float(self.strength_spin.value()),
            'channel': int(self.channel_combo.currentIndex()),
            'direction': int(self.direction_combo.currentIndex()),
            'wrap_mode': int(self.wrap_combo.currentIndex()),
            'invert': bool(self.invert_check.isChecked()),
            'center': bool(self.center_check.isChecked()),
            'scale': float(self.scale_spin.value()),
            'layer_name': self.name_edit.currentText(),
            'create_above': bool(self.create_above_check.isChecked())
        }

    def find_layer_by_name(self, node, name):
        if node.name() == name:
            return node
        for c in node.childNodes():
            r = self.find_layer_by_name(c, name)
            if r:
                return r
        return None