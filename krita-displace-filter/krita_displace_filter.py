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

from .displace_dialog import DisplaceDialog

class DisplaceFilterExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        pass

    def createActions(self, window):
        action = window.createAction("apply_displace_map", "Apply Displace Map", "tools/scripts")
        action.triggered.connect(self.apply_displace)

    # -------------------- STATIC HELPERS (Restored/Modified for Full Resolution) --------------------

    # NOTE: _srgb_to_linear is assumed to be available in DisplaceDialog.
    # If not, add it here or ensure DisplaceDialog is modified.

    @staticmethod
    def _srgb_to_linear(val_norm):
        """Applies sRGB EOTF (gamma removal) to get LINEAR value."""
        if val_norm <= 0.04045:
            return val_norm / 12.92
        else:
            return math.pow((val_norm + 0.055) / 1.055, 2.4)

    @staticmethod
    def _normalize_displacement_float(value_float, center, invert):
        """Normalize displacement float (0.0-1.0) value to range -1..1 or 0..1."""
        dn = value_float # Already normalized to 0.0-1.0

        if center:
            dn = (dn - 0.5) * 2.0  # Range: -1..1

        if invert:
            dn = -dn

        return dn



    def apply_displace(self):
        try:
            app = Krita.instance()
            doc = app.activeDocument()
            if not doc:
                QMessageBox.warning(None, "Error", "No active document.")
                return

            main_node = doc.activeNode()
            if not main_node or main_node.type() != 'paintlayer':
                QMessageBox.warning(None, "Error", "Select a paint layer.")
                return

            dialog = DisplaceDialog()
            if dialog.exec_() != QDialog.Accepted:
                return

            settings = dialog.get_settings()
            w = doc.width()
            h = doc.height()

            disp_node = self.find_layer_by_name(doc.rootNode(), settings['displacement_layer'])
            if not disp_node:
                QMessageBox.warning(None, "Error", f"Displacement layer '{settings['displacement_layer']}' not found.")
                return

            doc.setBatchmode(True)

            # Получение данных один раз
            src_data = main_node.pixelData(0, 0, w, h)
            disp_data = disp_node.pixelData(0, 0, w, h)

            if not src_data or not disp_data:
                doc.setBatchmode(False)
                QMessageBox.warning(None, "Error", "Cannot read pixel data from one of the layers.")
                return

            src_mv = memoryview(src_data)
            disp_mv = memoryview(disp_data)

            # Проверка BPC
            expected_pixels = w * h * 4
            bpc = len(src_mv) // expected_pixels
            if bpc not in (1, 2, 4):
                doc.setBatchmode(False)
                QMessageBox.warning(None, "Error", f"Unsupported bytes-per-channel: {bpc}")
                return

            # -------------------- ПРЕДВАРИТЕЛЬНЫЕ ВЫЧИСЛЕНИЯ --------------------

            # Константы для цикла
            strength_val = settings['strength'] * settings['scale']
            wrap_mode = settings['wrap_mode']
            direction = settings['direction']
            center = settings['center']
            invert = settings['invert']
            channel_idx = settings['channel']

            stride = 4 * bpc
            w_stride = w * stride
            data_len = len(src_mv)

            MAX_U8 = 255.0
            MAX_U16 = 65535.0

            # Предварительно вычислим функции для быстрого доступа
            srgb_to_linear = self._srgb_to_linear
            normalize_disp = self._normalize_displacement_float

            # -------------------- СПЕЦИАЛИЗИРОВАННЫЙ ЧИТАТЕЛЬ (Оптимизация 2) --------------------

            # Создаем функцию для чтения, специфичную для BPC, чтобы избежать проверок if/else в цикле
            if bpc == 1:
                # U8 Data (sRGB -> Linear)
                def get_disp_val(idx, disp_mv, channel_idx):
                    r_norm = disp_mv[idx + 2] / MAX_U8
                    g_norm = disp_mv[idx + 1] / MAX_U8
                    b_norm = disp_mv[idx] / MAX_U8

                    # Convert to LINEAR
                    r = srgb_to_linear(r_norm)
                    g = srgb_to_linear(g_norm)
                    b = srgb_to_linear(b_norm)

                    # Extract component
                    if channel_idx == 3: # Luminosity
                        return 0.299 * r + 0.587 * g + 0.114 * b
                    elif channel_idx == 0: # Red
                        return r
                    elif channel_idx == 1: # Green
                        return g
                    else: # Blue
                        return b

            elif bpc == 2:
                # U16 Data (Assumed Linear)
                def get_disp_val(idx, disp_mv, channel_idx):
                    # Используем struct.unpack для U16 (6 байт на RGB)
                    # '<HHH' - B G R
                    b, g, r = struct.unpack('<HHH', disp_mv[idx : idx + 6])

                    r /= MAX_U16
                    g /= MAX_U16
                    b /= MAX_U16

                    if channel_idx == 3: # Luminosity
                        return 0.299 * r + 0.587 * g + 0.114 * b
                    elif channel_idx == 0: # Red
                        return r
                    elif channel_idx == 1: # Green
                        return g
                    else: # Blue
                        return b

            elif bpc == 4:
                # F32 Data (Assumed Linear)
                def get_disp_val(idx, disp_mv, channel_idx):
                    # Используем struct.unpack для F32 (12 байт на RGB)
                    # '<fff' - B G R
                    b, g, r = struct.unpack('<fff', disp_mv[idx : idx + 12])

                    # Clamp to 0..1 for normalization (as in original code)
                    r = max(0.0, min(1.0, r))
                    g = max(0.0, min(1.0, g))
                    b = max(0.0, min(1.0, b))

                    if channel_idx == 3: # Luminosity
                        return 0.299 * r + 0.587 * g + 0.114 * b
                    elif channel_idx == 0: # Red
                        return r
                    elif channel_idx == 1: # Green
                        return g
                    else: # Blue
                        return b
            else:
                 # Должно быть обработано выше, но на всякий случай
                 return

            out_data = bytearray(data_len)
            out_mv = memoryview(out_data)

            # --- ГЛАВНЫЙ ЦИКЛ СМЕЩЕНИЯ (Ускоренный) ---
            for y in range(h):
                row_base = y * w
                for x in range(w):
                    idx = (row_base + x) * stride

                    # 1. Чтение и нормализация смещения (быстрый вызов)
                    dn_linear = get_disp_val(idx, disp_mv, channel_idx)
                    dn = normalize_disp(dn_linear, center, invert)
                    disp_scaled = strength_val * dn

                    # 2. Расчет координат
                    if direction == 0:  # Horizontal
                        sx_i = int(round(x + disp_scaled))
                        sy_i = y
                    elif direction == 1:  # Vertical
                        sx_i = x
                        sy_i = int(round(y + disp_scaled))
                    else:  # Both
                        sx_i = int(round(x + disp_scaled))
                        sy_i = int(round(y + disp_scaled))

                    # 3. Применение Wrap Mode (более чистый код)
                    if 0 <= sx_i < w and 0 <= sy_i < h:
                        # В пределах границ, ничего не делаем (Clamping по умолчанию)
                        pass
                    elif wrap_mode == 1:  # Wrap
                        sx_i %= w
                        sy_i %= h
                    elif wrap_mode == 2:  # Clamp (только если вышли за границы)
                        sx_i = max(0, min(w - 1, sx_i))
                        sy_i = max(0, min(h - 1, sy_i))

                    # 4. Сэмплирование Source Pixel и Запись
                    if 0 <= sx_i < w and 0 <= sy_i < h:
                        src_idx = (sy_i * w + sx_i) * stride

                        # КОПИРОВАНИЕ ЧЕРЕЗ СЛАЙСЫ memoryview (наиболее быстрое в Python)
                        out_mv[idx : idx + stride] = src_mv[src_idx : src_idx + stride]
                    else:
                        # Запись прозрачного (более чистое и быстрое обнуление)
                        # Используем memoryview для записи
                        out_mv[idx : idx + stride] = b'\x00' * stride


            # --- КОНЕЦ ГЛАВНОГО ЦИКЛА СМЕЩЕНИЯ ---

            new_node = main_node.clone()
            layer_name = settings['layer_name'].replace('{layer}', main_node.name())
            new_node.setName(layer_name)

            parent = main_node.parentNode()
            if settings['create_above']:
                parent.addChildNode(new_node, main_node)
            else:
                parent.addChildNode(new_node, None)

            # Write the resulting pixel data back to the new node
            new_node.setPixelData(bytes(out_data), 0, 0, w, h)
            doc.refreshProjection()
            doc.setBatchmode(False)

            try:
                doc.waitForDone()
            except:
                pass

        except Exception as e:
            if 'doc' in locals() and doc:
                doc.setBatchmode(False)
            QMessageBox.critical(None, "Plugin Error", str(e))

    def find_layer_by_name(self, node, name):
        if node.name() == name:
            return node
        for child in node.childNodes():
            result = self.find_layer_by_name(child, name)
            if result:
                return result
        return None


Krita.instance().addExtension(DisplaceFilterExtension(Krita.instance()))