"""Hauptfenster von DXFtoKRL."""
from __future__ import annotations

import os

from PySide6.QtCore import QRegularExpression, Qt, QTimer
from PySide6.QtGui import QAction, QFontDatabase, QKeySequence, QRegularExpressionValidator
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QSpinBox, QSplitter, QStackedWidget, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import __version__
from ..dxf_import import ImportResult, load_dxf
from ..geometry import Contour
from ..krl import KrlResult, generate, origin_shift, sanitize_name, write_files
from ..paths import chain_segments, optimize_order
from ..settings import Settings, save_settings
from .preview import PreviewView

PREVIEW_TOL = 0.05


def _fmt_time(sec: float) -> str:
    sec = int(round(sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d} h" if h else f"{m}:{s:02d} min"


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.import_result: ImportResult | None = None
        self.contours: list[Contour] = []
        self.result: KrlResult | None = None

        self._regen_timer = QTimer(self, singleShot=True, interval=250)
        self._regen_timer.timeout.connect(self.regenerate)
        self._rebuild_timer = QTimer(self, singleShot=True, interval=400)
        self._rebuild_timer.timeout.connect(self.rebuild_contours)
        self._reload_timer = QTimer(self, singleShot=True, interval=600)
        self._reload_timer.timeout.connect(self.reload)

        self.setWindowTitle("DXFtoKRL")
        self.resize(1400, 850)
        self.setAcceptDrops(True)
        self._build_actions()
        self._build_ui()
        self._update_title()
        self.regenerate()

    # ------------------------------------------------------------ Aufbau
    def _build_actions(self) -> None:
        tb = self.addToolBar("Werkzeuge")
        tb.setMovable(False)
        a_open = QAction("DXF öffnen…", self, shortcut=QKeySequence.Open, triggered=self.open_dialog)
        a_export = QAction("KRL exportieren…", self, shortcut=QKeySequence("Ctrl+E"), triggered=self.export)
        a_fit = QAction("Ansicht einpassen", self, shortcut=QKeySequence("F"), triggered=lambda: self.preview.fit())
        a_opt = QAction("Reihenfolge optimieren", self, triggered=self.optimize)
        for a in (a_open, a_export):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(a_opt)
        tb.addAction(a_fit)

        menu = self.menuBar().addMenu("&Datei")
        menu.addAction(a_open)
        menu.addAction(a_export)
        menu.addSeparator()
        menu.addAction(QAction("Beenden", self, shortcut=QKeySequence.Quit, triggered=self.close))
        view = self.menuBar().addMenu("&Ansicht")
        view.addAction(a_fit)
        help_menu = self.menuBar().addMenu("&Hilfe")
        help_menu.addAction(QAction("Über DXFtoKRL", self, triggered=self.about))

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([280, 760, 360])
        self.setCentralWidget(splitter)
        self.status = QLabel("Keine DXF geladen – Datei öffnen oder ins Fenster ziehen.")
        self.statusBar().addWidget(self.status, 1)

    def _build_left(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)

        lay.addWidget(QLabel("<b>Layer</b>"))
        self.layer_list = QListWidget()
        self.layer_list.setMaximumHeight(170)
        self.layer_list.itemChanged.connect(lambda _i: self._rebuild_timer.start())
        lay.addWidget(self.layer_list)

        lay.addWidget(QLabel("<b>Konturen</b> (Reihenfolge = Bearbeitung)"))
        self.contour_list = QListWidget()
        self.contour_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.contour_list.currentRowChanged.connect(self._on_contour_selected)
        self.contour_list.itemChanged.connect(self._on_contour_checked)
        lay.addWidget(self.contour_list, 1)

        row = QHBoxLayout()
        for text, tip, fn in (("▲", "Nach oben", lambda: self.move_contour(-1)),
                              ("▼", "Nach unten", lambda: self.move_contour(1)),
                              ("⇄", "Richtung umkehren", self.reverse_contour)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        b_opt = QPushButton("Reihenfolge optimieren")
        b_opt.clicked.connect(self.optimize)
        lay.addWidget(b_opt)
        return w

    def _build_center(self) -> QWidget:
        self.tabs = QTabWidget()
        self.preview = PreviewView()
        self.preview.contourClicked.connect(self.contour_list.setCurrentRow)
        self.tabs.addTab(self.preview, "Vorschau")
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.src_view = QPlainTextEdit(readOnly=True)
        self.dat_view = QPlainTextEdit(readOnly=True)
        for v in (self.src_view, self.dat_view):
            v.setFont(mono)
            v.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.tabs.addTab(self.src_view, "KRL .src")
        self.tabs.addTab(self.dat_view, "KRL .dat")
        return self.tabs

    # --- Formular-Helfer
    def _dspin(self, obj, attr, lo, hi, dec=2, suffix="", step=1.0, on_change=None, tip=""):
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(dec)
        sb.setSingleStep(step)
        sb.setSuffix(suffix)
        sb.setValue(getattr(obj, attr))
        sb.setToolTip(tip)
        sb.setKeyboardTracking(False)
        cb = on_change or self._regen_timer.start
        sb.valueChanged.connect(lambda v: (setattr(obj, attr, float(v)), cb()))
        return sb

    def _ispin(self, obj, attr, lo, hi, suffix="", special="", tip=""):
        sb = QSpinBox()
        sb.setRange(lo, hi)
        sb.setSuffix(suffix)
        if special:
            sb.setSpecialValueText(special)
        sb.setValue(getattr(obj, attr))
        sb.setToolTip(tip)
        sb.setKeyboardTracking(False)
        sb.valueChanged.connect(lambda v: (setattr(obj, attr, int(v)), self._regen_timer.start()))
        return sb

    def _check(self, obj, attr, text, on_change=None):
        cb = QCheckBox(text)
        cb.setChecked(getattr(obj, attr))
        fn = on_change or self._regen_timer.start
        cb.toggled.connect(lambda v: (setattr(obj, attr, bool(v)), fn()))
        return cb

    def _build_right(self) -> QWidget:
        g, m, p = self.settings.general, self.settings.milling, self.settings.plasma
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6, 6, 6, 6)

        # Profil
        top = QFormLayout()
        self.profile_box = QComboBox()
        self.profile_box.addItem("Plasmaschneiden", "plasma")
        self.profile_box.addItem("Fräsen", "milling")
        self.profile_box.setCurrentIndex(0 if self.settings.profile == "plasma" else 1)
        top.addRow("Profil:", self.profile_box)
        name = self.name_edit = QLineEdit(g.program_name)
        name.setValidator(QRegularExpressionValidator(QRegularExpression(r"[A-Za-z][A-Za-z0-9_]{0,23}")))
        name.setToolTip("KRL-Programmname = Dateiname (max. 24 Zeichen, Buchstabe zuerst)")
        name.textChanged.connect(lambda t: (setattr(g, "program_name", t), self._regen_timer.start()))
        top.addRow("Programmname:", name)
        lay.addLayout(top)

        # Roboter
        box = QGroupBox("Roboter")
        f = QFormLayout(box)
        f.addRow("BASE-Nr.:", self._ispin(g, "base_no", 0, 32))
        f.addRow("TOOL-Nr.:", self._ispin(g, "tool_no", 0, 16))
        tip = "Werkzeugausrichtung in BASE (konstant). KUKA: Werkzeug-X = Stoßrichtung, B=90° → nach unten."
        f.addRow("A:", self._dspin(g, "a", -180, 180, 3, " °", tip=tip))
        f.addRow("B:", self._dspin(g, "b", -180, 180, 3, " °", tip=tip))
        f.addRow("C:", self._dspin(g, "c", -180, 180, 3, " °", tip=tip))
        f.addRow("PTP-Geschw.:", self._ispin(g, "ptp_vel", 1, 100, " %"))
        f.addRow("", self._check(g, "use_home", "Start/Ende auf HOME (XHOME)"))
        lay.addWidget(box)

        # Bahn allgemein
        box = QGroupBox("Bahn")
        f = QFormLayout(box)
        f.addRow("Sicherheitshöhe Z:", self._dspin(g, "safe_z", -2000, 2000, 2, " mm",
                                                   tip="Absolute Höhe in BASE für Leerfahrten"))
        f.addRow("Oberfläche Z:", self._dspin(g, "surface_z", -2000, 2000, 2, " mm",
                                              tip="Werkstückoberfläche in BASE"))
        f.addRow("Leerfahrt:", self._dspin(g, "travel_speed", 1, 120000, 0, " mm/min", 500))
        f.addRow("Überschleifen:", self._dspin(g, "apo_cdis", 0, 50, 2, " mm", 0.1,
                                               tip="$APO.CDIS – Überschleifabstand zwischen Bahnstücken"))
        lay.addWidget(box)

        # Nullpunkt
        box = QGroupBox("Nullpunkt")
        f = QFormLayout(box)
        origin = QComboBox()
        origin.addItem("wie in DXF", "dxf")
        origin.addItem("linke untere Ecke der Teile", "bbox_min")
        origin.setCurrentIndex(0 if g.origin_mode == "dxf" else 1)
        origin.currentIndexChanged.connect(
            lambda _i: (setattr(g, "origin_mode", origin.currentData()), self._regen_timer.start()))
        f.addRow("Bezug:", origin)
        f.addRow("Versatz X:", self._dspin(g, "offset_x", -5000, 5000, 3, " mm"))
        f.addRow("Versatz Y:", self._dspin(g, "offset_y", -5000, 5000, 3, " mm"))
        lay.addWidget(box)

        # Prozess
        self.stack = QStackedWidget()
        # Plasma
        box = QGroupBox("Plasma")
        f = QFormLayout(box)
        f.addRow("Ausgang Brenner:", self._ispin(p, "torch_out", 0, 4096, special="– keiner –"))
        f.addRow("Eingang Lichtbogen OK:", self._ispin(p, "arc_ok_in", 0, 4096, special="– keiner –",
                                                       tip="Ohne Eingang wird nach dem Einschalten nur die Durchstechzeit gewartet"))
        f.addRow("Zünd-Timeout:", self._dspin(p, "arc_timeout", 0.1, 60, 1, " s", 0.5))
        f.addRow("Timer-Nr.:", self._ispin(p, "timer_no", 1, 32, tip="$TIMER[] für den Zünd-Timeout"))
        f.addRow("Ausgang Höhenregelung:", self._ispin(p, "thc_out", 0, 4096, special="– keiner –",
                                                       tip="Wird nach dem Absenken auf Schneidhöhe gesetzt"))
        f.addRow("Durchstechhöhe:", self._dspin(p, "pierce_height", 0, 100, 2, " mm", 0.5))
        f.addRow("Durchstechzeit:", self._dspin(p, "pierce_delay", 0, 30, 2, " s", 0.1))
        f.addRow("Schneidhöhe:", self._dspin(p, "cut_height", 0, 100, 2, " mm", 0.1))
        f.addRow("Absenken:", self._dspin(p, "plunge_feed", 1, 60000, 0, " mm/min", 50))
        f.addRow("Schneidvorschub:", self._dspin(p, "feed", 1, 60000, 0, " mm/min", 100))
        f.addRow("Nachlauf:", self._dspin(p, "post_delay", 0, 30, 2, " s", 0.1,
                                          tip="Wartezeit nach Brenner aus, vor dem Abheben"))
        self.stack.addWidget(box)
        # Fräsen
        box = QGroupBox("Fräsen")
        f = QFormLayout(box)
        f.addRow("Ausgang Spindel:", self._ispin(m, "spindle_out", 0, 4096, special="– keiner –"))
        f.addRow("Hochlaufzeit:", self._dspin(m, "spindle_delay", 0, 60, 1, " s", 0.5))
        f.addRow("Frästiefe:", self._dspin(m, "depth", 0, 200, 2, " mm", 0.5))
        f.addRow("Zustellung:", self._dspin(m, "step_down", 0, 200, 2, " mm", 0.5,
                                            tip="Tiefe je Durchgang (0 = in einem Durchgang)"))
        f.addRow("Annäherung:", self._dspin(m, "approach", 0, 100, 2, " mm", 0.5,
                                            tip="Bis zu diesem Abstand über der Oberfläche im Eilgang"))
        f.addRow("Eintauchvorschub:", self._dspin(m, "plunge_feed", 1, 60000, 0, " mm/min", 50))
        f.addRow("Fräsvorschub:", self._dspin(m, "feed", 1, 60000, 0, " mm/min", 100))
        self.stack.addWidget(box)
        lay.addWidget(self.stack)
        self.stack.setCurrentIndex(self.profile_box.currentIndex())
        self.profile_box.currentIndexChanged.connect(self._on_profile)

        # Import
        box = QGroupBox("Import")
        f = QFormLayout(box)
        f.addRow("Verbinden bis:", self._dspin(g, "chain_tol", 0.001, 5, 3, " mm", 0.01,
                                               on_change=self._rebuild_timer.start,
                                               tip="Enden, die näher beieinander liegen, werden zu einer Kontur verbunden"))
        f.addRow("Spline-Genauigkeit:", self._dspin(g, "flatten_tol", 0.001, 1, 3, " mm", 0.01,
                                                    on_change=self._reload_timer.start,
                                                    tip="Max. Abweichung beim Zerlegen von Splines/Ellipsen"))
        f.addRow("", self._check(g, "rotate_start", "Startpunkt geschlossener Konturen optimieren"))
        lay.addWidget(box)

        note = QLabel("Stufe 1: Bahn = Werkzeugmitte, ohne Radius-/Schnittspaltkorrektur "
                      "und ohne An-/Abfahrbahnen.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #8a5a00;")
        lay.addWidget(note)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMinimumWidth(330)
        return scroll

    # ------------------------------------------------------------ Laden
    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "DXF öffnen", self.settings.last_dir,
                                              "DXF-Dateien (*.dxf *.DXF);;Alle Dateien (*)")
        if path:
            self.load_dxf(path)

    def load_dxf(self, path: str) -> None:
        try:
            result = load_dxf(path, self.settings.general.flatten_tol)
        except Exception as exc:
            QMessageBox.critical(self, "Fehler beim Lesen", f"Die Datei konnte nicht gelesen werden:\n{exc}")
            return
        self.import_result = result
        self.settings.last_dir = os.path.dirname(path)
        base = os.path.splitext(os.path.basename(path))[0]
        self.settings.general.program_name = sanitize_name(base)
        self.name_edit.blockSignals(True)
        self.name_edit.setText(self.settings.general.program_name)
        self.name_edit.blockSignals(False)
        self._fill_layers()
        self.rebuild_contours(fit=True)
        self._update_title()
        msgs = list(result.warnings)
        if result.unit_factor != 1.0:
            msgs.insert(0, f"Zeichnungseinheit {result.unit_name} → umgerechnet in mm.")
        if result.skipped:
            msgs.append("Nicht verwendet: " + ", ".join(f"{n}× {t}" for t, n in result.skipped.most_common()))
        if msgs:
            self.statusBar().showMessage(" | ".join(msgs), 15000)

    def reload(self) -> None:
        if not self.import_result:
            return
        checked = self._checked_layers()
        try:
            self.import_result = load_dxf(self.import_result.path, self.settings.general.flatten_tol)
        except Exception as exc:
            QMessageBox.critical(self, "Fehler beim Lesen", str(exc))
            return
        self._fill_layers(checked)
        self.rebuild_contours()

    def _fill_layers(self, checked: set[str] | None = None) -> None:
        r = self.import_result
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for layer in sorted(r.layer_counts, key=str.lower):
            item = QListWidgetItem(f"{layer}  ({r.layer_counts[layer]})")
            item.setData(Qt.UserRole, layer)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            on = (layer in checked) if checked is not None else (layer not in r.layers_off)
            item.setCheckState(Qt.Checked if on else Qt.Unchecked)
            self.layer_list.addItem(item)
        self.layer_list.blockSignals(False)

    def _checked_layers(self) -> set[str]:
        return {self.layer_list.item(i).data(Qt.UserRole)
                for i in range(self.layer_list.count())
                if self.layer_list.item(i).checkState() == Qt.Checked}

    def rebuild_contours(self, fit: bool = False) -> None:
        if not self.import_result:
            return
        layers = self._checked_layers()
        segs = [(l, s) for l, s in self.import_result.segments if l in layers]
        contours = chain_segments(segs, self.settings.general.chain_tol)
        self.contours = contours
        self.optimize(refresh=False)
        self._refresh(fit=fit)

    # ------------------------------------------------------------ Konturen
    def _origin_dxf(self) -> tuple[float, float]:
        dx, dy = origin_shift(self.contours, self.settings)
        return (-dx, -dy)

    def optimize(self, refresh: bool = True) -> None:
        if not self.contours:
            return
        self.contours = optimize_order(self.contours, self._origin_dxf(),
                                       self.settings.general.rotate_start)
        if refresh:
            self._refresh()

    def move_contour(self, delta: int) -> None:
        i = self.contour_list.currentRow()
        j = i + delta
        if i < 0 or not (0 <= j < len(self.contours)):
            return
        self.contours[i], self.contours[j] = self.contours[j], self.contours[i]
        self._refresh(select=j)

    def reverse_contour(self) -> None:
        i = self.contour_list.currentRow()
        if 0 <= i < len(self.contours):
            self.contours[i] = self.contours[i].reversed()
            self._refresh(select=i)

    def _on_contour_checked(self, item: QListWidgetItem) -> None:
        i = self.contour_list.row(item)
        if 0 <= i < len(self.contours):
            self.contours[i].enabled = item.checkState() == Qt.Checked
            self._refresh(select=i, rebuild_list=False)

    def _on_contour_selected(self, row: int) -> None:
        self.preview.set_selected(row)

    def _fill_contour_list(self, select: int) -> None:
        self.contour_list.blockSignals(True)
        self.contour_list.clear()
        for i, c in enumerate(self.contours, 1):
            item = QListWidgetItem(f"{i:>3}  {c.describe()}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if c.enabled else Qt.Unchecked)
            self.contour_list.addItem(item)
        self.contour_list.blockSignals(False)
        if 0 <= select < len(self.contours):
            self.contour_list.setCurrentRow(select)

    def _refresh(self, fit: bool = False, select: int = -1, rebuild_list: bool = True) -> None:
        if rebuild_list:
            self._fill_contour_list(select)
        self.regenerate(fit=fit)
        self.preview.set_selected(self.contour_list.currentRow())

    def _on_profile(self, idx: int) -> None:
        self.settings.profile = self.profile_box.itemData(idx)
        self.stack.setCurrentIndex(idx)
        self.regenerate()

    # ------------------------------------------------------------ KRL
    def regenerate(self, fit: bool = False) -> None:
        source = self.import_result.path if self.import_result else ""
        self.result = generate(self.contours, self.settings, source)
        sel = self.contour_list.currentRow()
        self.preview.set_contours(self.contours, self._origin_dxf(), PREVIEW_TOL)
        self.preview.set_selected(sel)
        if fit:
            QTimer.singleShot(0, self.preview.fit)
        self.src_view.setPlainText(self.result.src)
        self.dat_view.setPlainText(self.result.dat)
        r = self.result
        if self.contours:
            active = sum(1 for c in self.contours if c.enabled)
            text = (f"{active}/{len(self.contours)} Konturen  |  Schnittweg {r.cut_length:,.0f} mm  |  "
                    f"Leerweg {r.travel_length:,.0f} mm  |  ca. {_fmt_time(r.est_time)}  |  "
                    f"{r.lines} Zeilen").replace(",", ".")
            if r.warnings:
                text += "  |  ⚠ " + " ".join(r.warnings)
            self.status.setText(text)

    def export(self) -> None:
        self.regenerate()
        r = self.result
        if not self.contours or not any(c.enabled for c in self.contours):
            QMessageBox.information(self, "Export", "Keine aktiven Konturen zum Exportieren.")
            return
        if r.warnings:
            ans = QMessageBox.warning(self, "Hinweise", "\n\n".join(r.warnings) + "\n\nTrotzdem exportieren?",
                                      QMessageBox.Yes | QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        start = self.settings.export_dir or self.settings.last_dir
        directory = QFileDialog.getExistingDirectory(self, "Zielordner für .src/.dat", start)
        if not directory:
            return
        existing = [n for n in (r.name + ".src", r.name + ".dat") if os.path.exists(os.path.join(directory, n))]
        if existing:
            ans = QMessageBox.question(self, "Überschreiben?", "Bereits vorhanden:\n" + "\n".join(existing)
                                       + "\n\nÜberschreiben?")
            if ans != QMessageBox.Yes:
                return
        try:
            src, dat = write_files(r, directory)
        except OSError as exc:
            QMessageBox.critical(self, "Fehler", f"Schreiben fehlgeschlagen:\n{exc}")
            return
        self.settings.export_dir = directory
        save_settings(self.settings)
        self.statusBar().showMessage(f"Gespeichert: {src}  und  {os.path.basename(dat)}", 10000)

    # ------------------------------------------------------------ Sonstiges
    def _update_title(self) -> None:
        name = os.path.basename(self.import_result.path) if self.import_result else "keine Datei"
        self.setWindowTitle(f"DXFtoKRL – {name}")

    def about(self) -> None:
        QMessageBox.about(self, "Über DXFtoKRL",
                          f"<b>DXFtoKRL {__version__}</b><br>DXF → KUKA KRL (KR C2) für Fräsen und Plasmaschneiden.<br><br>"
                          "Erzeugte Programme immer zuerst in T1 mit reduzierter Geschwindigkeit testen.")

    def dragEnterEvent(self, event):
        if any(u.toLocalFile().lower().endswith(".dxf") for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for u in event.mimeData().urls():
            if u.toLocalFile().lower().endswith(".dxf"):
                self.load_dxf(u.toLocalFile())
                break

    def closeEvent(self, event):
        save_settings(self.settings)
        super().closeEvent(event)
