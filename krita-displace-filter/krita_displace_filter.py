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

    def _read_disp_channel_linear_float(self, disp_mv, idx, bpc, settings):
        """
        Reads the displacement channel (R, G, B, or Luma) at full resolution
        and returns its LINEAR float value in the range [0.0, 1.0].
        This replaces the complex get_normalized_displacement logic.
        """
        channel_idx = settings['channel']

        if bpc == 4:
            # F32 data must be read as float
            b = struct.unpack('<f', disp_mv[idx : idx + 4])[0]
            g = struct.unpack('<f', disp_mv[idx + 4 : idx + 8])[0]
            r = struct.unpack('<f', disp_mv[idx + 8 : idx + 12])[0]

            # Clamp to 0..1 for normalization
            r = max(0.0, min(1.0, r))
            g = max(0.0, min(1.0, g))
            b = max(0.0, min(1.0, b))

        elif bpc == 2:
            # U16 data (Assumed LINEAR by default in Krita for high bit depth)
            b = disp_mv[idx] | (disp_mv[idx + 1] << 8)
            g = disp_mv[idx + 2] | (disp_mv[idx + 3] << 8)
            r = disp_mv[idx + 4] | (disp_mv[idx + 5] << 8)

            MAX_U16 = 65535.0
            r /= MAX_U16
            g /= MAX_U16
            b /= MAX_U16

        else: # bpc == 1
            # U8 data (CRITICAL: sRGB -> LINEAR conversion)
            MAX_U8 = 255.0
            r_norm = disp_mv[idx + 2] / MAX_U8
            g_norm = disp_mv[idx + 1] / MAX_U8
            b_norm = disp_mv[idx] / MAX_U8

            r = self._srgb_to_linear(r_norm)
            g = self._srgb_to_linear(g_norm)
            b = self._srgb_to_linear(b_norm)

        # Extract displacement component (R, G, B, or Luma)
        if channel_idx == 3: # Luminosity (using 0-1 floats)
            d = 0.299 * r + 0.587 * g + 0.114 * b
        elif channel_idx == 0: # Red
            d = r
        elif channel_idx == 1: # Green
            d = g
        else: # Blue
            d = b

        return d


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

            src_data = main_node.pixelData(0, 0, w, h)
            disp_data = disp_node.pixelData(0, 0, w, h)

            if not src_data or not disp_data:
                doc.setBatchmode(False)
                QMessageBox.warning(None, "Error", "Cannot read pixel data from one of the layers.")
                return

            src_mv = memoryview(src_data)
            disp_mv = memoryview(disp_data)

            expected_pixels = w * h * 4
            if len(src_mv) % expected_pixels != 0:
                doc.setBatchmode(False)
                QMessageBox.warning(None, "Error", "Unexpected pixel data size (source).")
                return

            bpc = len(src_mv) // expected_pixels
            if bpc not in (1, 2, 4):
                doc.setBatchmode(False)
                QMessageBox.warning(None, "Error", f"Unsupported bytes-per-channel: {bpc}")
                return


            strength = settings['strength'] * settings['scale']
            wrap_mode = settings['wrap_mode']
            direction = settings['direction']
            center = settings['center']
            invert = settings['invert']

            stride = 4 * bpc
            w_stride = w * stride


            out_data = bytearray(len(src_mv))
            out_mv = memoryview(out_data)

            # --- MAIN DISPLACEMENT LOOP (Optimized) ---
            for y in range(h):
                row_base = y * w
                for x in range(w):
                    idx = (row_base + x) * stride

                    # dn is the LINEAR displacement component, normalized to [0.0, 1.0]
                    dn_linear = self._read_disp_channel_linear_float(disp_mv, idx, bpc, settings)

                    dn = self._normalize_displacement_float(dn_linear, center, invert)

                    disp_scaled = strength * dn

                    if direction == 0:  # Horizontal
                        sx, sy = x + disp_scaled, y
                    elif direction == 1:  # Vertical
                        sx, sy = x, y + disp_scaled
                    else:  # Both
                        sx, sy = x + disp_scaled, y + disp_scaled

                    # 4. Apply Wrap Mode (Inlined apply_wrap_mode)
                    sx_i = int(round(sx))
                    sy_i = int(round(sy))

                    if wrap_mode == 1:  # Wrap
                        sx_i %= w
                        sy_i %= h
                    elif wrap_mode == 2:  # Clamp
                        sx_i = max(0, min(w - 1, sx_i))
                        sy_i = max(0, min(h - 1, sy_i))

                    # 5. Sample Source Pixel and Write to Output
                    if 0 <= sx_i < w and 0 <= sy_i < h:
                        src_idx = (sy_i * w + sx_i) * stride

                        # Copy pixel data slice-by-slice for performance
                        out_mv[idx : idx + stride] = src_mv[src_idx : src_idx + stride]
                    else:
                        # Write transparent (optimized by bpc)
                        if bpc == 1:
                            out_mv[idx:idx+4] = b'\x00\x00\x00\x00'
                        elif bpc == 2:
                            out_mv[idx:idx+8] = b'\x00' * 8
                        else: # bpc == 4 (F32)
                            out_mv[idx:idx+16] = struct.pack('<ffff', 0.0, 0.0, 0.0, 0.0) # Explicit float zero

            # --- END MAIN DISPLACEMENT LOOP ---

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