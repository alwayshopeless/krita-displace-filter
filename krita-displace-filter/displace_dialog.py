from krita import *
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QComboBox, QPushButton,
    QCheckBox, QGroupBox, QSlider
)
from PyQt5.QtCore import Qt, QTimer, QSettings
from PyQt5.QtGui import QImage, QPixmap
import struct
import time
import math
import array

class DisplaceDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Displace Map Filter")
        self.setMinimumWidth(700)

        self.doc = None

        # Caching for scaled (preview size) data
        self.cached_src_scaled_data = None
        self.cached_disp_scaled_data = None
        self.cached_preview_scale = 0.0
        self.cached_w = 0
        self.cached_h = 0

        # Settings persistence
        self.settings = QSettings("Krita", "DisplaceMapFilter")

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

        # Auto-update checkbox
        self.auto_update_check = QCheckBox("Auto-update on settings change")
        self.auto_update_check.setChecked(True)
        preview_layout.addWidget(self.auto_update_check)

        # Manual update button
        self.manual_update_btn = QPushButton("Refresh Preview Now")
        self.manual_update_btn.setEnabled(False)
        self.manual_update_btn.clicked.connect(lambda: self.schedule_preview_update(immediate=True))
        preview_layout.addWidget(self.manual_update_btn)

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

        # Quick scale buttons
        buttons_layout = QHBoxLayout()
        for scale_pct in [10, 25, 50, 75, 100]:
            btn = QPushButton(f"{scale_pct}%")
            btn.clicked.connect(lambda checked, s=scale_pct: self.set_preview_scale(s))
            buttons_layout.addWidget(btn)
        preview_layout.addLayout(buttons_layout)

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

        s_layout = QHBoxLayout()
        s_layout.addWidget(QLabel("Strength:"))
        self.strength_spin = QDoubleSpinBox()
        self.strength_spin.setRange(0.0, 5000.0)
        self.strength_spin.setValue(100.0)
        self.strength_spin.setSingleStep(1.0)
        self.strength_spin.valueChanged.connect(self.schedule_preview_update)
        s_layout.addWidget(self.strength_spin)
        settings_layout.addLayout(s_layout)

        ch_layout = QHBoxLayout()
        ch_layout.addWidget(QLabel("Channel:"))
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Red", "Green", "Blue", "Luminosity"])
        self.channel_combo.currentIndexChanged.connect(self.schedule_preview_update)
        ch_layout.addWidget(self.channel_combo)
        settings_layout.addLayout(ch_layout)

        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Direction:"))
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["Horizontal", "Vertical", "Both"])
        self.direction_combo.currentIndexChanged.connect(self.schedule_preview_update)
        dir_layout.addWidget(self.direction_combo)
        settings_layout.addLayout(dir_layout)

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

        # --- Output ---
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

        self.last_preview_time = 0
        self.preview_throttle_ms = 200

        self.load_settings()


    def load_settings(self):
        """Load previously saved settings."""
        self.strength_spin.setValue(self.settings.value("strength", 100.0, type=float))
        self.channel_combo.setCurrentIndex(self.settings.value("channel", 0, type=int))
        self.direction_combo.setCurrentIndex(self.settings.value("direction", 0, type=int))
        self.wrap_combo.setCurrentIndex(self.settings.value("wrap_mode", 0, type=int))
        self.invert_check.setChecked(self.settings.value("invert", False, type=bool))
        self.center_check.setChecked(self.settings.value("center", True, type=bool))
        self.auto_update_check.setChecked(self.settings.value("auto_update", True, type=bool))
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
        self.settings.setValue("auto_update", self.auto_update_check.isChecked())
        self.settings.setValue("scale", self.scale_spin.value())
        self.settings.setValue("preview_scale", self.preview_scale)
        self.settings.setValue("preview_enabled", self.preview_enabled)
        self.settings.setValue("layer_name", self.name_edit.currentText())
        self.settings.setValue("create_above", self.create_above_check.isChecked())

    def accept(self):
        self.save_settings()
        super().accept()

    def reject(self):
        self.save_settings()
        super().reject()

    # -------------------- Helpers and Layer Logic --------------------

    def on_layer_changed(self):
        """Handle layer change: invalidate scaled cache and schedule update."""
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
        self.manual_update_btn.setEnabled(self.preview_enabled)

        if self.preview_enabled:
            self.preview_label.clear()
            self.schedule_preview_update(immediate=True)
        else:
            self.preview_label.setText("Preview disabled.\nEnable checkbox above to see preview.")
            self.preview_timer.stop()

    def on_preview_scale_changed(self, v):
        self.preview_scale = max(0.01, v / 100.0)
        self.scale_label.setText(f"{v}%")

        self.cached_src_scaled_data = None
        self.cached_disp_scaled_data = None
        self.cached_preview_scale = 0.0

        if self.preview_enabled:
            self.schedule_preview_update(immediate=True)

    def set_preview_scale(self, scale_pct):
        """Set preview scale from button click"""
        self.scale_slider.setValue(scale_pct)

    def schedule_preview_update(self, immediate=False):
        if not self.preview_enabled:
            return

        is_auto_update_enabled = self.auto_update_check.isChecked()
        if not immediate and not is_auto_update_enabled:
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

    # -------------------- Data Loading (Memory Optimized) --------------------

    def get_scaled_preview_data(self):
        """
        Loads data in native color depth, converts to 8-bit RGB for preview,
        then scales using QImage.scaled().
        """

        # Check if cache is valid
        if (self.cached_src_scaled_data and
            self.cached_preview_scale == self.preview_scale and
            self.cached_w > 0):
            return self.cached_src_scaled_data, self.cached_disp_scaled_data, self.cached_w, self.cached_h

        doc = Krita.instance().activeDocument()
        if not doc:
            raise RuntimeError("No active document")

        node = doc.activeNode()
        disp_layer_name = self.layer_combo.currentText()
        disp_node = self.find_layer_by_name(doc.rootNode(), disp_layer_name)

        if not node or not disp_node:
             raise RuntimeError(f"Active layer or displacement layer '{disp_layer_name}' not found.")

        w_orig, h_orig = doc.width(), doc.height()

        # Определяем глубину цвета документа
        color_depth = doc.colorDepth()

        # Получаем данные в нативной глубине цвета
        src_raw = node.projectionPixelData(0, 0, w_orig, h_orig)
        disp_raw = disp_node.projectionPixelData(0, 0, w_orig, h_orig)

        if not src_raw or not disp_raw:
             raise RuntimeError("Cannot read projection pixel data.")

        # Конвертируем в 8-bit RGBA для превью
        src_u8 = self.convert_to_u8_rgba(src_raw, w_orig, h_orig, color_depth)
        disp_u8 = self.convert_to_u8_rgba(disp_raw, w_orig, h_orig, color_depth)

        # Создание полноразмерных QImage
        src_qimage_full = QImage(src_u8, w_orig, h_orig, w_orig * 4, QImage.Format_ARGB32)
        disp_qimage_full = QImage(disp_u8, w_orig, h_orig, w_orig * 4, QImage.Format_ARGB32)

        # Освобождение памяти
        del src_raw
        del disp_raw
        del src_u8
        del disp_u8

        # Масштабирование
        pw = max(1, int(w_orig * self.preview_scale))
        ph = max(1, int(h_orig * self.preview_scale))

        src_scaled = src_qimage_full.scaled(pw, ph, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        disp_scaled = disp_qimage_full.scaled(pw, ph, Qt.IgnoreAspectRatio, Qt.FastTransformation)

        del src_qimage_full
        del disp_qimage_full

        # Кэширование
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

    def convert_to_u8_rgba(self, raw_data, width, height, color_depth):
        """
        Конвертирует пиксельные данные из различных форматов в 8-bit RGBA.
        Применяет линейно-sRGB конверсию для корректного отображения.
        """
        pixel_count = width * height

        if color_depth == "U8":
            # Уже в 8-bit формате, просто возвращаем
            # Примечание: предполагаем, что U8 данные уже в sRGB.
            return raw_data

        elif color_depth == "U16":
            # 16-bit на канал: конвертируем в 8-bit с sRGB коррекцией
            result = bytearray(pixel_count * 4)
            MAX_U16 = 65535.0

            for i in range(pixel_count):
                # Krita хранит в формате BGRA
                offset = i * 8  # 4 канала * 2 байта

                # Читаем 16-bit значения (little-endian)
                b_u16 = struct.unpack_from('<H', raw_data, offset)[0]
                g_u16 = struct.unpack_from('<H', raw_data, offset + 2)[0]
                r_u16 = struct.unpack_from('<H', raw_data, offset + 4)[0]
                a_u16 = struct.unpack_from('<H', raw_data, offset + 6)[0]

                # Нормализуем в 0.0-1.0 (линейное пространство)
                r_linear = r_u16 / MAX_U16
                g_linear = g_u16 / MAX_U16
                b_linear = b_u16 / MAX_U16
                a_linear = a_u16 / MAX_U16

                # Применяем линейно-sRGB конверсию для RGB каналов
                result[i*4] = self._linear_to_srgb_u8(b_linear)      # B
                result[i*4+1] = self._linear_to_srgb_u8(g_linear)    # G
                result[i*4+2] = self._linear_to_srgb_u8(r_linear)    # R
                # Альфа-канал остается линейным, просто масштабируем до 8-бит
                result[i*4+3] = max(0, min(255, int(a_linear * 255 + 0.5)))    # A

            return bytes(result)

        elif color_depth == "F16" or color_depth == "F32":
            # (Оставляем ваш код для float, он уже использует _linear_to_srgb_u8)
            # ... (ваш существующий код для F16/F32) ...
            # Ваш код для F16/F32 выглядит корректно
            bytes_per_channel = 2 if color_depth == "F16" else 4
            format_char = 'e' if color_depth == "F16" else 'f'

            result = bytearray(pixel_count * 4)
            for i in range(pixel_count):
                offset = i * 4 * bytes_per_channel

                # Читаем float значения (линейное пространство)
                b = struct.unpack_from('<' + format_char, raw_data, offset)[0]
                g = struct.unpack_from('<' + format_char, raw_data, offset + bytes_per_channel)[0]
                r = struct.unpack_from('<' + format_char, raw_data, offset + bytes_per_channel * 2)[0]
                a = struct.unpack_from('<' + format_char, raw_data, offset + bytes_per_channel * 3)[0]

                # Применяем линейно-sRGB конверсию для RGB каналов
                result[i*4] = self._linear_to_srgb_u8(b)      # B
                result[i*4+1] = self._linear_to_srgb_u8(g)    # G
                result[i*4+2] = self._linear_to_srgb_u8(r)    # R
                # Альфа остается линейной
                result[i*4+3] = max(0, min(255, int(a * 255 + 0.5)))    # A

            return bytes(result)

        else:
            # Неизвестный формат - пробуем как 8-bit
            print(f"Warning: Unknown color depth '{color_depth}', treating as U8")
            return raw_data

    @staticmethod
    def _linear_to_srgb_u8(linear_val):
        """Конвертирует линейное значение (0.0-1.0) в sRGB u8 (0-255)"""
        # Клампим значение
        linear_val = max(0.0, min(1.0, linear_val))

        # Применяем sRGB гамма-коррекцию
        if linear_val <= 0.0031308:
            srgb = 12.92 * linear_val
        else:
            srgb = 1.055 * math.pow(linear_val, 1.0 / 2.4) - 0.055

        # Конвертируем в 8-bit
        return max(0, min(255, int(srgb * 255 + 0.5)))

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
            NORM_CENTER_MULT = 2.0 / MAX_VAL
            NORM_CENTER_OFFSET = 1.0
        else:
            NORM_CENTER_MULT = 1.0 / MAX_VAL
            NORM_CENTER_OFFSET = 0.0
        INV_SIGN = -1.0 if invert else 1.0

        out_data = bytearray(pw * ph * 4)
        pw_4 = pw * 4

        for y in range(ph):
            row_base = y * pw_4
            for x in range(pw):
                idx = row_base + x * 4

                b = disp_data[idx]
                g = disp_data[idx + 1]
                r = disp_data[idx + 2]

                if channel_idx == 3:
                    d_val = 0.299 * r + 0.587 * g + 0.114 * b
                elif channel_idx == 0:
                    d_val = float(r)
                elif channel_idx == 1:
                    d_val = float(g)
                else:
                    d_val = float(b)

                dn = (d_val * NORM_CENTER_MULT) - NORM_CENTER_OFFSET if center else d_val * NORM_CENTER_MULT
                disp_px = dn * INV_SIGN * strength

                if direction == 0:
                    sx, sy = x + disp_px, y
                elif direction == 1:
                    sx, sy = x, y + disp_px
                else:
                    sx, sy = x + disp_px, y + disp_px

                sx_i = int(round(sx))
                sy_i = int(round(sy))

                if wrap_mode == 1:
                    sx_i %= pw
                    sy_i %= ph
                elif wrap_mode == 2:
                    sx_i = max(0, min(pw - 1, sx_i))
                    sy_i = max(0, min(ph - 1, sy_i))

                if 0 <= sx_i < pw and 0 <= sy_i < ph:
                    src_idx = (sy_i * pw + sx_i) * 4
                    out_data[idx:idx+4] = src_data[src_idx:src_idx+4]
                else:
                    pass

        out_image = QImage(bytes(out_data), pw, ph, pw * 4, QImage.Format_ARGB32)

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