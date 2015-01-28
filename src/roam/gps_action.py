import os

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.QtSvg import QSvgRenderer

from qgis.core import *
from qgis.gui import *

from roam import resources_rc, utils
from roam.utils import log
from roam.api import RoamEvents, GPS

import roam.config

if os.name == 'nt':
    try:
        from power import PowerState

        powerenabled = True
    except ImportError as ex:
        utils.warning("Can't load Power management support {}".format(ex))
        powerenabled = False


class GPSAction(QAction):
    gpsfixed = pyqtSignal(bool)

    def __init__(self, icon, canvas, parent):
        super(GPSAction, self).__init__(QIcon(icon),
                                        QApplication.translate("GPSAction", "GPS", None,
                                                               QApplication.UnicodeUTF8),
                                        parent)
        self.canvas = canvas
        self.triggered.connect(self.connectGPS)
        GPS.gpsfixed.connect(self.fixed)
        GPS.gpsfailed.connect(self.failed)
        GPS.gpsdisconnected.connect(self.disconnected)

    def updateGPSPort(self):
        print GPS.isConnected
        print roam.config.settings['gpsport']
        print GPS.currentport

        if GPS.isConnected and not roam.config.settings['gpsport'] == GPS.currentport:
            GPS.disconnectGPS()
            self.connectGPS()

    def connectGPS(self):
        if not GPS.isConnected:
            # Enable GPS
            self.setIcon(QIcon(":/icons/gps"))
            self.setIconText(self.tr("Connecting.."))
            self.setEnabled(False)
            portname = roam.config.settings.get("gpsport", '')
            GPS.connectGPS(portname)
        else:
            GPS.disconnectGPS()

    def disconnected(self):
        self.setIcon(QIcon(":/icons/gps"))
        self.setIconText("Enable GPS")
        self.setEnabled(True)

    def connected(self, gpsConnection):
        self.setIcon(QIcon(':/icons/gps_looking'))
        self.setIconText("Searching")
        self.setEnabled(True)

    def failed(self):
        self.setEnabled(True)
        log("GPS Failed to connect")
        self.setIcon(QIcon(':/icons/gps_failed'))
        self.setIconText("GPS Failed. Click to retry")

    def fixed(self, fixed, gpsInfo):
        if fixed:
            self.setIcon(QIcon(':/icons/gps_on'))
            self.setIconText("GPS Fixed")
            self.setEnabled(True)
        else:
            self.setIcon(QIcon(':/icons/gps_failed'))
            self.setIconText("No fix yet")


class GPSMarker(QgsMapCanvasItem):
    def __init__(self, canvas):
        super(GPSMarker, self).__init__(canvas)
        self.canvas = canvas
        self._quaility = 0
        self.size = 24
        self.red = Qt.darkRed
        self.blue = QColor(129, 173, 210)
        self.green = Qt.darkGreen

        self.pointbrush = QBrush(self.red)
        self.pointpen = QPen(self.red)
        self.map_pos = QgsPoint(0.0, 0.0)

    def setSize(self, size):
        self.size = size

    def paint(self, painter, xxx, xxx2):
        self.setPos(self.toCanvasCoordinates(self.map_pos))

        halfSize = self.size / 2.0
        rect = QRectF(0 - halfSize, 0 - halfSize, self.size, self.size)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.quality == 0:
            color = self.red
        elif self.quality == 1:
            color = self.blue
        elif self.quality >= 2:
            color = self.green
        else:
            color = self.red

        self.pointpen.setColor(color)
        self.pointbrush.setColor(color)

        painter.setBrush(self.pointbrush)
        painter.setPen(self.pointpen)
        painter.drawEllipse(rect)

    def boundingRect(self):
        halfSize = self.size / 2.0
        return QRectF(-halfSize, -halfSize, 2.0 * halfSize, 2.0 * halfSize)

    @property
    def quality(self):
        return self._quaility

    @quality.setter
    def quality(self, value):
        self._quaility = value
        self.update()

    def setCenter(self, map_pos):
        self.map_pos = map_pos
        self.setPos(self.toCanvasCoordinates(self.map_pos))

    def updatePosition(self):
        self.setCenter(self.map_pos)
