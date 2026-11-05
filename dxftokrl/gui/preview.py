"""2D-Vorschau der Bahn (Zoom mit Mausrad, Verschieben mit Ziehen, Klick wählt Kontur)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem,
                               QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView)

from ..geometry import Contour, Point

COL_CUT = QColor("#1f5fbf")
COL_SEL = QColor("#d62828")
COL_OFF = QColor("#b8b8b8")
COL_TRAVEL = QColor("#8a8a8a")
COL_START = QColor("#2a9d3f")


def _pen(color: QColor, width: float = 1.5, style=Qt.SolidLine) -> QPen:
    pen = QPen(color, width, style)
    pen.setCosmetic(True)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    return pen


def _arrow_path() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(14, 0)
    p.lineTo(4, -5)
    p.lineTo(4, 5)
    p.closeSubpath()
    return p


class PreviewView(QGraphicsView):
    contourClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#ffffff")))
        self.scale(1, -1)  # DXF: Y nach oben
        self._items: list[QGraphicsPathItem] = []
        self._contours: list[Contour] = []
        self._selected = -1

    # ------------------------------------------------------------------
    def set_contours(self, contours: list[Contour], origin: Point, tol: float = 0.05) -> None:
        scene = self.scene()
        scene.clear()
        self._items = []
        self._contours = contours

        # Leerfahrten
        travel = QPainterPath()
        prev = origin
        for c in contours:
            if not c.enabled:
                continue
            travel.moveTo(QPointF(*prev))
            travel.lineTo(QPointF(*c.start))
            prev = c.end
        t_item = scene.addPath(travel, _pen(COL_TRAVEL, 1.0, Qt.DashLine))
        t_item.setZValue(-1e9)

        nr = 0
        for i, c in enumerate(contours):
            pts = c.points(tol)
            path = QPainterPath(QPointF(*pts[0]))
            for p in pts[1:]:
                path.lineTo(QPointF(*p))
            item = scene.addPath(path, _pen(COL_CUT if c.enabled else COL_OFF))
            item.setData(0, i)
            x0, y0, x1, y1 = c.bbox(tol)
            item.setZValue(-(x1 - x0) * (y1 - y0))  # kleine Konturen oben -> anklickbar
            self._items.append(item)
            if not c.enabled:
                continue
            nr += 1
            self._marker(c, str(nr))

        cross = QPainterPath()
        cross.moveTo(-10, 0); cross.lineTo(10, 0)
        cross.moveTo(0, -10); cross.lineTo(0, 10)
        o = scene.addPath(cross, _pen(QColor("#e07b00"), 2))
        o.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        o.setPos(QPointF(*origin))
        o.setToolTip("Nullpunkt BASE")
        self._apply_selection()

    def _marker(self, c: Contour, label: str) -> None:
        scene = self.scene()
        sx, sy = c.start
        dot = QGraphicsEllipseItem(-3.5, -3.5, 7, 7)
        dot.setBrush(QBrush(COL_START))
        dot.setPen(QPen(Qt.NoPen))
        dot.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        dot.setPos(sx, sy)
        dot.setZValue(10)
        scene.addItem(dot)

        tx, ty = c.start_tangent()
        arrow = QGraphicsPathItem(_arrow_path())
        arrow.setBrush(QBrush(COL_START))
        arrow.setPen(QPen(Qt.NoPen))
        arrow.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        arrow.setPos(sx, sy)
        arrow.setRotation(-math.degrees(math.atan2(ty, tx)))
        arrow.setZValue(10)
        scene.addItem(arrow)

        text = QGraphicsSimpleTextItem(label)
        text.setBrush(QBrush(QColor("#333333")))
        text.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        text.setPos(sx, sy)
        text.setZValue(11)
        scene.addItem(text)

    def set_selected(self, index: int) -> None:
        self._selected = index
        self._apply_selection()

    def _apply_selection(self) -> None:
        for i, item in enumerate(self._items):
            c = self._contours[i]
            if i == self._selected:
                item.setPen(_pen(COL_SEL, 3))
            else:
                item.setPen(_pen(COL_CUT if c.enabled else COL_OFF, 1.5))

    def fit(self) -> None:
        rect = QRectF()
        for item in self._items:
            rect = rect.united(item.sceneBoundingRect())
        if rect.isEmpty():
            return
        m = max(rect.width(), rect.height()) * 0.05 + 1
        self.fitInView(rect.adjusted(-m, -m, m, m), Qt.KeepAspectRatio)

    # ------------------------------------------------------------------
    def wheelEvent(self, event):
        factor = 1.0015 ** event.angleDelta().y()
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item is not None and item.data(0) is not None:
                self.contourClicked.emit(int(item.data(0)))
        super().mousePressEvent(event)
