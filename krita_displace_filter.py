# krita_displace_plugin.py
# Оптимизированный Displace Map plugin для Krita с расширенным UI
# Установка: ~/.local/share/krita/pykrita/displace_plugin/

from krita import *
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QDoubleSpinBox, QComboBox, QPushButton, 
                             QCheckBox, QGroupBox, QSpinBox, QMessageBox)
from PyQt5.QtCore import Qt

class DisplaceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Displace Map Filter")
        self.setMinimumWidth(400)
        
        main_layout = QVBoxLayout(self)
        
        # d-map selection
        layer_group = QGroupBox("Displacement Map Layer")
        layer_layout = QVBoxLayout()
        
        self.layer_combo = QComboBox()
        self.populate_layers()
        layer_layout.addWidget(self.layer_combo)

        # update layer list
        refresh_btn = QPushButton("Refresh Layer List")
        refresh_btn.clicked.connect(self.populate_layers)
        layer_layout.addWidget(refresh_btn)
        
        layer_group.setLayout(layer_layout)
        main_layout.addWidget(layer_group)
        
        # common settings
        settings_group = QGroupBox("Displacement Settings")
        settings_layout = QVBoxLayout()
        
        # Strength
        strength_layout = QHBoxLayout()
        strength_layout.addWidget(QLabel("Strength:"))
        self.strength_spin = QDoubleSpinBox()
        self.strength_spin.setRange(0.0, 500.0)
        self.strength_spin.setValue(100.0)
        self.strength_spin.setSingleStep(0.05)
        self.strength_spin.setDecimals(2)
        strength_layout.addWidget(self.strength_spin)
        settings_layout.addLayout(strength_layout)
        
        # Channel selection
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Displacement Channel:"))
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Red", "Green", "Blue", "Luminosity"])
        channel_layout.addWidget(self.channel_combo)
        settings_layout.addLayout(channel_layout)
        
        # Direction
        direction_layout = QHBoxLayout()
        direction_layout.addWidget(QLabel("Direction:"))
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["Horizontal", "Vertical", "Both"])
        direction_layout.addWidget(self.direction_combo)
        settings_layout.addLayout(direction_layout)
        
        # Wrap mode
        wrap_layout = QHBoxLayout()
        wrap_layout.addWidget(QLabel("Edge Handling:"))
        self.wrap_combo = QComboBox()
        self.wrap_combo.addItems([ "Clamp", "Transparent", "Wrap"])
        wrap_layout.addWidget(self.wrap_combo)
        settings_layout.addLayout(wrap_layout)
        
        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)
        
        # === Advanced Options ===
        advanced_group = QGroupBox("Advanced Options")
        advanced_layout = QVBoxLayout()
        
        self.invert_check = QCheckBox("Invert Displacement")
        advanced_layout.addWidget(self.invert_check)
        
        self.center_check = QCheckBox("Center Displacement (0.5 = no displacement)")
        self.center_check.setChecked(True)
        advanced_layout.addWidget(self.center_check)
        
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("Scale:"))
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.01, 10.0)
        self.scale_spin.setValue(1.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setDecimals(2)
        scale_layout.addWidget(self.scale_spin)
        advanced_layout.addLayout(scale_layout)
        
        advanced_group.setLayout(advanced_layout)
        main_layout.addWidget(advanced_group)
        
        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout()
        
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("New Layer Name:"))
        self.name_edit = QComboBox()
        self.name_edit.setEditable(True)
        self.name_edit.addItems([
            "{layer}_displaced",
            "{layer}_displace",
            "Displaced",
            "Custom..."
        ])
        name_layout.addWidget(self.name_edit)
        output_layout.addLayout(name_layout)
        
        self.create_above_check = QCheckBox("Create above active layer")
        self.create_above_check.setChecked(True)
        output_layout.addWidget(self.create_above_check)
        
        output_group.setLayout(output_layout)
        main_layout.addWidget(output_group)
        
        # === Buttons ===
        button_layout = QHBoxLayout()
        
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self.accept)
        button_layout.addWidget(apply_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        main_layout.addLayout(button_layout)

    def populate_layers(self):
        current = self.layer_combo.currentText()
        self.layer_combo.clear()
        
        doc = Krita.instance().activeDocument()
        if doc:
            layers = self.collect_paint_layers(doc.rootNode())
            for layer_name in layers:
                self.layer_combo.addItem(layer_name)
            
            idx = self.layer_combo.findText(current)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)

    def collect_paint_layers(self, node, layers=None):
        if layers is None:
            layers = []
        
        if node.type() == "paintlayer":
            layers.append(node.name())
        
        for child in node.childNodes():
            self.collect_paint_layers(child, layers)
        
        return layers

    def get_settings(self):
        return {
            'displacement_layer': self.layer_combo.currentText(),
            'strength': self.strength_spin.value(),
            'channel': self.channel_combo.currentIndex(),
            'direction': self.direction_combo.currentIndex(),
            'wrap_mode': self.wrap_combo.currentIndex(),
            'invert': self.invert_check.isChecked(),
            'center': self.center_check.isChecked(),
            'scale': self.scale_spin.value(),
            'layer_name': self.name_edit.currentText(),
            'create_above': self.create_above_check.isChecked()
        }


class DisplaceFilterExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        pass

    def createActions(self, window):
        action = window.createAction("apply_displace_map", "Apply Displace Map", "tools/scripts")
        action.triggered.connect(self.apply_displace)

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

            new_node = main_node.clone()
            layer_name = settings['layer_name'].replace('{layer}', main_node.name())
            new_node.setName(layer_name)
            
            if settings['create_above']:
                doc.rootNode().addChildNode(new_node, main_node)
            else:
                parent = main_node.parentNode()
                parent.addChildNode(new_node, None)

            src_data = bytes(main_node.pixelData(0, 0, w, h))
            disp_data = bytes(disp_node.pixelData(0, 0, w, h))

            if not src_data or not disp_data:
                QMessageBox.warning(None, "Error", "Cannot read pixel data.")
                return

            # Обработка
            out_data = bytearray(w * h * 4)
            
            strength = settings['strength']  * settings['scale']
            channel_idx = settings['channel']  # 0=R, 1=G, 2=B, 3=Lum
            direction = settings['direction']  # 0=H, 1=V, 2=Both
            wrap_mode = settings['wrap_mode']  # 0=Trans, 1=Wrap, 2=Clamp
            invert = settings['invert']
            center = settings['center']

            for y in range(h):
                row_off = y * w * 4
                
                for x in range(w):
                    idx = row_off + x * 4

                    if channel_idx == 3:  # Luminosity correction
                        r, g, b = disp_data[idx], disp_data[idx+1], disp_data[idx+2]
                        d = (0.299 * r + 0.587 * g + 0.114 * b)
                    else:
                        d = disp_data[idx + channel_idx]
                    
                    # normalisation displace value
                    d = d / 255
                    
                    # Center mode
                    if center:
                        d = (d - 0.5) * 2.0  # -1..1
                    
                    # Invert
                    if invert:
                        d = 1.0 - d if not center else -d


                    # scale displacement with invert displacement value
                    disp_scaled = strength * -d
                    
                    if direction == 0:  # Horizontal
                        sx = x + disp_scaled    
                        sy = y
                    elif direction == 1:  # Vertical
                        sx = x
                        sy = y + disp_scaled
                    else:  # Both
                        sx = x + disp_scaled
                        sy = y + disp_scaled
                    
                    sx = int(round(sx))
                    sy = int(round(sy))
                    
                    # layer borders processing
                    if wrap_mode == 1:  # Wrap
                        sx = sx % w
                        sy = sy % h
                    elif wrap_mode == 2:  # Clamp
                        sx = max(0, min(w-1, sx))
                        sy = max(0, min(h-1, sy))
                    
                    # map image data
                    if 0 <= sx < w and 0 <= sy < h:
                        src_idx = sy * w * 4 + sx * 4
                        out_data[idx:idx+4] = src_data[src_idx:src_idx+4]
                    else:
                        if wrap_mode == 0:  # Transparent
                            out_data[idx:idx+4] = b'\x00\x00\x00\x00'

            new_node.setPixelData(bytes(out_data), 0, 0, w, h)
            doc.refreshProjection()

        except Exception as e:
            QMessageBox.critical(None, "Plugin Error", str(e))

    """Search hint"""
    def find_layer_by_name(self, node, name):
        if node.name() == name:
            return node
        for child in node.childNodes():
            result = self.find_layer_by_name(child, name)
            if result:
                return result
        return None

Krita.instance().addExtension(DisplaceFilterExtension(Krita.instance()))
