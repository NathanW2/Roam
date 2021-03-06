"""
    Main plugin code for QMap
    #HACK This is OLD code. Ignore me.  Will be deleted once the port is done.
"""

import os
import resources_rc
import functools
import utils
import sys
import traceback
import getpass

from qgis.core import (QgsProjectBadLayerHandler, QgsMapLayerRegistry,
                       QgsMessageLog, QgsMapLayer, 
                       QgsProject, QgsTolerance, 
                       QgsFeature
                       )
from qgis.gui import QgsMessageBar, QgsRubberBand

from PyQt4.QtCore import QUrl, Qt, QSize, QFileInfo
from PyQt4.QtGui import (QIcon, QWidget, 
                         QActionGroup, QPushButton, 
                         QToolBar, QAction, 
                         QApplication, QMenuBar,
                         QGridLayout, QStackedWidget,
                         QSizePolicy, QMessageBox,
                         QToolButton, QProgressBar,
                         QLabel, QColor )

from gps_action import GPSAction
from maptools import (MoveTool, PointTool, 
                      EditTool, InfoTool)

from floatingtoolbar import FloatingToolBar
from dataentrywidget import DialogProvider
from project import QMapProject, NoMapToolConfigured, getProjects, ErrorInMapTool

from listfeatureform import ListFeaturesForm
from listmodulesdialog import ProjectsWidget
from popdialog import PopDownReport
from helpviewdialog import HelpPage
from settingswidget import SettingsWidget
from infodock import InfoDock

class BadLayerHandler( QgsProjectBadLayerHandler):
    def __init__( self, callback ):
        super(BadLayerHandler, self).__init__()
        self.callback = callback

    def handleBadLayers( self, domNodes, domDocument ):
        layers = [node.namedItem("layername").toElement().text() for node in domNodes]
        self.callback(layers)

class QMap():
    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.panels= []
        self.navtoolbar = self.iface.mapNavToolToolBar()
        self.mainwindow = self.iface.mainWindow()
        self.iface.projectRead.connect(self.projectOpened)
        self.iface.initializationCompleted.connect(self.setupUI)
        self.actionGroup = QActionGroup(self.mainwindow)
        self.actionGroup.setExclusive(True)
        self.menuGroup = QActionGroup(self.mainwindow)
        self.menuGroup.setExclusive(True)
                
        self.movetool = MoveTool(self.iface.mapCanvas(), [])
        self.infotool = InfoTool(self.iface.mapCanvas())
        self.infotool.infoResults.connect(self.showInfoResults)
        
        self.report = PopDownReport(self.iface.messageBar())
        
        self.dialogprovider = DialogProvider(iface.mapCanvas(), iface)
        self.dialogprovider.accepted.connect(self.clearToolRubberBand)
        self.dialogprovider.rejected.connect(self.clearToolRubberBand)
        
        self.edittool = EditTool(self.iface.mapCanvas(),[])
        self.edittool.finished.connect(self.openForm)
        self.edittool.featuresfound.connect(self.showFeatureSelection)

        self.infodock = InfoDock(self.iface.mainWindow())
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.infodock)
        self.infodock.hide()

        self.band = QgsRubberBand(self.iface.mapCanvas())
        self.band.setIconSize(20)
        self.band.setWidth(10)
        self.band.setColor(QColor(186, 93, 212, 76))

    def showFeatureSelection(self, features):
        listUi = ListFeaturesForm(self.mainwindow)
        listUi.loadFeatureList(features)
        listUi.openFeatureForm.connect(self.openForm)
        listUi.exec_()

    def showInfoResults(self, results):
        self.infodock.clearResults()
        self.infodock.setResults(results)
        self.infodock.show()
        self.infodock.repaint()
        
    @property
    def _mapLayers(self):
        return QgsMapLayerRegistry.instance().mapLayers()
        
    def clearToolRubberBand(self):
        tool = self.iface.mapCanvas().mapTool()
        try:
            tool.clearBand()
        except AttributeError:
            # No clearBand method found, but that's cool.
            pass
        
    def missingLayers(self, layers):
        def showError():
            html = ["<h1>Missing Layers</h1>", "<ul>"]
            for layer in layers:
                html.append("<li>{}</li>".format(layer))
            html.append("</ul>")
            
            self.errorreport.updateHTML("".join(html))
        
        message = "Seems like {} didn't load correctly".format(utils._pluralstring('layer', len(layers)))
        
        utils.warning("Missing layers")
        map(utils.warning, layers)
            
        self.widget = self.iface.messageBar().createMessage("Missing Layers",
                                                 message, 
                                                 QIcon(":/icons/sad"))
        button = QPushButton(self.widget)
        button.setCheckable(True)
        button.setChecked(self.errorreport.isVisible())
        button.setText("Show missing layers")
        button.toggled.connect(showError)
        button.toggled.connect(functools.partial(self.errorreport.setVisible))
        self.widget.destroyed.connect(self.hideReports)
        self.widget.layout().addWidget(button)
        self.iface.messageBar().pushWidget(self.widget, QgsMessageBar.WARNING)
        
    def excepthook(self, ex_type, value, tb):
        """ 
        Custom exception hook so that we can handle errors in a
        nicer way
        """
        where = ''.join(traceback.format_tb(tb))
        msg = '{}'.format(value)
        utils.critical(msg)
        
        def showError():
            html = """
                <html>
                <body bgcolor="#FFEDED">
                <p><b>{}</b></p>
                <p align="left"><small>{}</small></p>
                </body>
                </html>
            """.format(msg, where)
            self.errorreport.updateHTML(html)
        
        self.widget = self.iface.messageBar().createMessage("oops", "Looks like an error occurred", QIcon(":/icons/sad"))
        button = QPushButton(self.widget)
        button.setCheckable(True)
        button.setChecked(self.errorreport.isVisible())
        button.setText("Show error")
        button.toggled.connect(showError)
        button.toggled.connect(functools.partial(self.errorreport.setVisible))
        self.widget.destroyed.connect(self.hideReports)
        self.widget.layout().addWidget(button)
        self.messageBar.pushWidget(self.widget, QgsMessageBar.CRITICAL)
    
    def hideReports(self):
        self.errorreport.setVisible(False)
        self.report.setVisible(False)
    
    def setupUI(self):
        """
        Set up the main QGIS interface items.  Called after QGIS has loaded
        the plugin.
        """
        self.updateAppSize()
        
        utils.settings_notify.settings_changed.connect(self.updateAppSize)

        self.navtoolbar.setMovable(False)
        self.navtoolbar.setAllowedAreas(Qt.TopToolBarArea)
        
        self.mainwindow.insertToolBar(self.toolbar, self.navtoolbar)
        self.openProjectAction.trigger()
        
    def updateAppSize(self):
        fullscreen = utils.settings.get("fullscreen", False)
        if fullscreen:
            self.mainwindow.showFullScreen()
        else:
            self.mainwindow.showMaximized()
            
    def setMapTool(self, tool):
        """
        Set the current mapview canvas tool

        tool -- The QgsMapTool to set
        """
        self.iface.mapCanvas().setMapTool(tool)

    def createToolBars(self):
        """
        Create all the needed toolbars
        """
        
        self.menutoolbar = QToolBar("Menu", self.mainwindow)
        self.menutoolbar.setMovable(False)
        self.menutoolbar.setAllowedAreas(Qt.LeftToolBarArea)
        self.mainwindow.addToolBar(Qt.LeftToolBarArea, self.menutoolbar)
        
        self.toolbar = QToolBar("QMap", self.mainwindow)
        self.mainwindow.addToolBar(Qt.TopToolBarArea, self.toolbar)
        self.toolbar.setMovable(False)

        self.editingtoolbar = FloatingToolBar("Editing", self.toolbar)
        self.extraaddtoolbar = FloatingToolBar("Extra Add Tools", self.toolbar)
        self.syncactionstoolbar = FloatingToolBar("Syncing", self.toolbar)
        self.syncactionstoolbar.setOrientation(Qt.Vertical)

    def createActions(self):
        """
        Create all the actions
        """

        self.homeAction = (QAction(QIcon(":/icons/zoomfull"),
                                  "Default View", self.mainwindow))
        self.gpsAction = (GPSAction(QIcon(":/icons/gps"), self.iface.mapCanvas(),
                                   self.mainwindow))
        
        self.openProjectAction = (QAction(QIcon(":/icons/open"), "Projects",
                                         self.mainwindow))
        self.openProjectAction.setCheckable(True)
        
        self.configAction = (QAction(QIcon(":/icons/config"), "Settings",
                                         self.mainwindow))
        self.configAction.setCheckable(True)
        
        self.toggleRasterAction = (QAction(QIcon(":/icons/photo"), "Aerial Photos",
                                          self.mainwindow))
        self.syncAction = QAction(QIcon(":/icons/sync"), "Sync", self.mainwindow)
        self.syncAction.setVisible(False)
        
        self.editattributesaction = QAction(QIcon(":/icons/edit"), "Edit Attributes", self.mainwindow)
        self.editattributesaction.setCheckable(True)
        self.editattributesaction.toggled.connect(functools.partial(self.setMapTool, self.edittool))

        self.moveaction = QAction(QIcon(":/icons/move"), "Move Feature", self.mainwindow)
        self.moveaction.setCheckable(True)

        self.editingmodeaction = QAction(QIcon(":/icons/edittools"), "Edit Tools", self.mainwindow)
        self.editingmodeaction.setCheckable(True)
        
        self.infoaction = QAction(QIcon(":/icons/info"), "Info", self.mainwindow)
        self.infoaction.setCheckable(True)

        self.addatgpsaction = QAction(QIcon(":/icons/gpsadd"), "Add at GPS", self.mainwindow)
        
        self.edittool.layersupdated.connect(self.editattributesaction.setVisible)
        self.movetool.layersupdated.connect(self.moveaction.setVisible)
        self.movetool.layersupdated.connect(self.editingmodeaction.setVisible)
        
    def initGui(self):
        """
        Create all the icons and setup the tool bars.  Called by QGIS when
        loading. This is called before setupUI.
        """
        QApplication.setWindowIcon(QIcon(":/branding/logo"))
        self.mainwindow.findChildren(QMenuBar)[0].setVisible(False)
        self.mainwindow.setContextMenuPolicy(Qt.PreventContextMenu)
        self.mainwindow.setWindowTitle("IntraMaps Roam: Mobile Data Collection")
        
        # Disable QGIS logging window popups. We do our own logging
        QgsMessageLog.instance().messageReceived.disconnect()
        
        s = """
        QToolButton { 
            padding: 6px;
            color: #4f4f4f;
         }
        
        QToolButton:hover { 
            padding: 6px;
            background-color: rgb(211, 228, 255);
         }
         
        QToolBar {
         background: white;
        }
        
        QCheckBox::indicator {
             width: 40px;
             height: 40px;
         }
        
        QLabel {
            color: #4f4f4f;
        }
        
        QDialog { background-color: rgb(255, 255, 255); }
        
        QPushButton { 
            border: 1px solid #e1e1e1;
             padding: 6px;
            color: #4f4f4f;
         }
        
        QPushButton:hover { 
            border: 1px solid #e1e1e1;
             padding: 6px;
            background-color: rgb(211, 228, 255);
         }
        
        QCheckBox {
            color: #4f4f4f;
        }
        
        QComboBox::drop-down {
            width: 30px;
        }
        
        QComboBox {
            border: 1px solid #d3d3d3;
        }

        QStackedWidget {
             background-color: rgb(255, 255, 255);
        }
        """
        self.mainwindow.setStyleSheet(s)
        
        mainwidget = self.mainwindow.centralWidget()
        mainwidget.setLayout(QGridLayout())
        mainwidget.layout().setContentsMargins(0,0,0,0)
        
        newlayout = QGridLayout()
        newlayout.setContentsMargins(0,0,0,0)
        newlayout.addWidget(self.iface.mapCanvas(), 0,0,2,1)
        newlayout.addWidget(self.iface.messageBar(), 0,0,1,1)
        
        wid = QWidget()
        wid.setLayout(newlayout)
        
        self.stack = QStackedWidget(self.mainwindow)
        self.messageBar = QgsMessageBar(wid)
        self.messageBar.setSizePolicy( QSizePolicy.Minimum, QSizePolicy.Fixed )
        self.errorreport = PopDownReport(self.messageBar)

        mainwidget.layout().addWidget(self.stack, 0,0,2,1)
        mainwidget.layout().addWidget(self.messageBar, 0,0,1,1)

        self.helppage = HelpPage()
        helppath = os.path.join(os.path.dirname(__file__) , 'help',"help.html")
        self.helppage.setHelpPage(helppath)
        
        self.settingswidget = SettingsWidget(self.stack)
        
        self.projectwidget = ProjectsWidget()   
        self.projectwidget.requestOpenProject.connect(self.loadProject)
        self.stack.addWidget(wid)
        self.stack.addWidget(self.projectwidget)
        self.stack.addWidget(self.helppage)
        self.stack.addWidget(self.settingswidget)
                
        sys.excepthook = self.excepthook

        def createSpacer(width=30):
            widget = QWidget()
            widget.setMinimumWidth(width)
            return widget

        self.createToolBars()
        self.createActions()

        spacewidget = createSpacer(60)
        gpsspacewidget = createSpacer()
        gpsspacewidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.moveaction.toggled.connect(functools.partial(self.setMapTool, self.movetool))
        self.infoaction.toggled.connect(functools.partial(self.setMapTool, self.infotool))
        
        showediting = (functools.partial(self.editingtoolbar.showToolbar, 
                                         self.editingmodeaction,
                                         self.moveaction))
        self.editingmodeaction.toggled.connect(showediting)

        self.addatgpsaction.triggered.connect(self.addAtGPS)
        self.addatgpsaction.setEnabled(self.gpsAction.isConnected)
        self.gpsAction.gpsfixed.connect(self.addatgpsaction.setEnabled)

        self.editingtoolbar.addToActionGroup(self.moveaction)

        self.actionGroup.addAction(self.editingmodeaction)
        self.actionGroup.addAction(self.editattributesaction)
        self.actionGroup.addAction(self.infoaction)

        self.homeAction.triggered.connect(self.zoomToDefaultView)
        
        self.openProjectAction.triggered.connect(self.showOpenProjectDialog)
        self.openProjectAction.triggered.connect(functools.partial(self.stack.setCurrentIndex, 1))
        
        self.configAction.triggered.connect(functools.partial(self.stack.setCurrentIndex, 3))
        self.configAction.triggered.connect(self.settingswidget.populateControls)
        self.configAction.triggered.connect(self.settingswidget.readSettings)
        
        self.toggleRasterAction.triggered.connect(self.toggleRasterLayers)

        self.navtoolbar.insertAction(self.iface.actionZoomIn(), self.iface.actionTouch())
        self.navtoolbar.insertAction(self.iface.actionTouch(), self.homeAction)
        self.navtoolbar.insertAction(self.iface.actionTouch(), self.iface.actionZoomFullExtent())
        self.navtoolbar.insertAction(self.homeAction, self.iface.actionZoomFullExtent())

        self.navtoolbar.addAction(self.toggleRasterAction)
        self.navtoolbar.insertWidget(self.iface.actionZoomFullExtent(), spacewidget)
        self.toolbar.addAction(self.infoaction)
        self.toolbar.addAction(self.editingmodeaction)
        self.toolbar.addAction(self.editattributesaction)
        self.toolbar.addAction(self.syncAction)
        self.toolbar.addAction(self.gpsAction)
        self.toolbar.insertWidget(self.syncAction, gpsspacewidget)
        self.toolbar.insertSeparator(self.gpsAction)

        self.extraaddtoolbar.addAction(self.addatgpsaction)

        self.editingtoolbar.addAction(self.moveaction)
        
        self.mapview = QAction(QIcon(":/icons/map"), "Map", self.menutoolbar)
        self.mapview.setCheckable(True)
        self.mapview.triggered.connect(functools.partial(self.stack.setCurrentIndex, 0))
        
        self.help = QAction(QIcon(":/icons/help"), "Help", self.menutoolbar)
        self.help.setCheckable(True)
        self.help.triggered.connect(functools.partial(self.stack.setCurrentIndex, 2))
        self.help.setVisible(False)
        
        self.projectlabel = QLabel("Project: <br> None")
        self.projectlabel.setAlignment(Qt.AlignCenter)
        self.projectlabel.setStyleSheet("""
            QLabel {
                    color: #8c8c8c;
                    font: 10px "Calibri" ;
                    }""")

        self.userlabel = QLabel("User: <br> {user}".format(user=getpass.getuser()))
        self.userlabel.setAlignment(Qt.AlignCenter)
        self.userlabel.setStyleSheet("""
            QLabel {
                    color: #8c8c8c;
                    font: 10px "Calibri" ;
                    }""")
        
        self.quit = QAction(QIcon(":/icons/quit"), "Quit", self.menutoolbar)
        self.quit.triggered.connect(self.iface.actionExit().trigger)

        self.menuGroup.addAction(self.mapview)
        self.menuGroup.addAction(self.openProjectAction)
        self.menuGroup.addAction(self.help)
        self.menuGroup.addAction(self.configAction)
        
        self.menutoolbar.addAction(self.mapview)
        self.menutoolbar.addAction(self.openProjectAction)
        self.menutoolbar.addAction(self.help)
        self.menutoolbar.addAction(self.configAction)
        self.menutoolbar.addAction(self.quit)
        
        quitspacewidget = createSpacer()
        quitspacewidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        labelaction = self.menutoolbar.insertWidget(self.configAction, self.userlabel)
        
        self.menutoolbar.insertWidget(labelaction, quitspacewidget)
        self.menutoolbar.insertWidget(labelaction, self.projectlabel)
        self.setupIcons()
        self.stack.currentChanged.connect(self.updateUIState)
        
    def updateUIState(self, page):
        """
        Update the UI state to reflect the currently selected
        page in the stacked widget
        """
        def setToolbarsActive(enabled):
            toolbars = self.mainwindow.findChildren(QToolBar)
            for toolbar in toolbars:
                if toolbar == self.menutoolbar:
                    continue
                toolbar.setEnabled(enabled)
        
        def setPanelsVisible(visible):
            for panel in self.panels:
                panel.setVisible(visible)
                
        ismapview = page == 0
        setToolbarsActive(ismapview)
        setPanelsVisible(ismapview)
        self.infodock.hide()

    def addAtGPS(self):
        """
        Add a record at the current GPS location.
        """
        action = self.actionGroup.checkedAction()
        if not action:
            return
        layer = action.data()
        if not layer:
            return
        
        point = self.gpsAction.position
        self.addNewFeature(layer=layer, geometry=point)
        
    def zoomToDefaultView(self):
        """
        Zoom the mapview canvas to the extents the project was opened at i.e. the
        default extent.
        """
        self.iface.mapCanvas().setExtent(self.defaultextent)
        self.iface.mapCanvas().refresh()

    def toggleRasterLayers(self):
        """
        Toggle all raster layers on or off.
        """
        legend = self.iface.legendInterface()
        #Freeze the canvas to save on UI refresh
        self.iface.mapCanvas().freeze()
        for layer in self._mapLayers.values():
            if layer.type() == QgsMapLayer.RasterLayer:
                isvisible = legend.isLayerVisible(layer)
                legend.setLayerVisible(layer, not isvisible)
        self.iface.mapCanvas().freeze(False)
        self.iface.mapCanvas().refresh()

    def setupIcons(self):
        """
        Update toolbars to have text and icons, change normal QGIS
        icons to new style
        """
        toolbars = self.mainwindow.findChildren(QToolBar)
        for toolbar in toolbars:
            toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            toolbar.setIconSize(QSize(32, 32))

        self.iface.actionTouch().setIconText("Pan")
        self.iface.actionTouch().setIcon(QIcon(":/icons/pan"))
        self.iface.actionZoomIn().setIcon(QIcon(":/icons/in"))
        self.iface.actionZoomOut().setIcon(QIcon(":/icons/out"))
        self.iface.actionPan().setIcon(QIcon(":/icons/pan"))
        self.iface.actionZoomFullExtent().setIcon(QIcon(":/icons/home"))
        self.iface.actionZoomFullExtent().setIconText("Home View")

        self.actionGroup.addAction(self.iface.actionZoomIn())
        self.actionGroup.addAction(self.iface.actionZoomOut())
        self.actionGroup.addAction(self.iface.actionTouch())

    def projectOpened(self):
        """
            Called when a new project is opened in QGIS.
        """
        for panel in self.panels:
            self.mainwindow.removeDockWidget(panel)
            del panel

        projectpath = QgsProject.instance().fileName()
        project = QMapProject(os.path.dirname(projectpath), self.iface)
        self.projectlabel.setText("Project: <br> {}".format(project.name))
        self.createFormButtons(projectlayers = project.getConfiguredLayers())
        
        # Enable the raster layers button only if the project contains a raster layer.
        hasrasters = any(layer.type() for layer in self._mapLayers.values())
        self.toggleRasterAction.setEnabled(hasrasters)
        self.defaultextent = self.iface.mapCanvas().extent()
        self.connectSyncProviders(project)
        
        # Show panels
        self.panels = list(project.getPanels())
        for panel in self.panels:
            self.mainwindow.addDockWidget(Qt.BottomDockWidgetArea , panel)
            
        self.iface.messageBar().popWidget()

    def captureLayer(self, layer):
        text = layer.icontext
        tool = layer.getMaptool(self.iface.mapCanvas())

        # Hack until I fix it later
        if isinstance(tool, PointTool):
            add = functools.partial(self.addNewFeature, qgslayer)
            tool.geometryComplete.connect(add)
        else:
            tool.finished.connect(self.openForm)
            tool.error.connect(functools.partial(self.showToolError, text))

        action = QAction(QIcon(layer.icon), text, self.mainwindow)
        action.setData(layer)
        action.setCheckable(True)
        action.toggled.connect(functools.partial(self.setMapTool, tool))

        self.toolbar.insertAction(self.editingmodeaction, action)

        if not tool.isEditTool():
            # Connect the GPS tools strip to the action pressed event.
            showgpstools = (functools.partial(self.extraaddtoolbar.showToolbar,
                                         action,
                                         None))

            action.toggled.connect(showgpstools)

        self.actionGroup.addAction(action)
        self.actions.append(action)

    def editLayer(self, layer):
        self.edittool.addLayer(layer.QGISLayer)
        self.edittool.searchRadius = 10

    def moveLayer(self, layer):
        self.movetool.addLayer(layer.QGISLayer)

    def createFormButtons(self, projectlayers):
        """
            Create buttons for each form that is definded
        """
        # Remove all the old buttons
        for action in self.actions:
            self.actionGroup.removeAction(action)
            self.toolbar.removeAction(action)
                
        self.edittool.layers = []
        self.movetool.layers = []
        capabilitityhandlers = { "capture" : self.captureLayer,
                                 "edit" : self.editLayer,
                                 "move" : self.moveLayer}

        for layer in projectlayers:
            try:
                qgslayer = QgsMapLayerRegistry.instance().mapLayersByName(layer.name)[0]
                if qgslayer.type() == QgsMapLayer.RasterLayer:
                    utils.log("We can't support raster layers for data entry")
                    continue
                       
                layer.QGISLayer = qgslayer
            except IndexError:
                utils.log("Layer {} not found in project".format(layer.name))
                continue

            for capability in layer.capabilities:
                try:
                    capabilitityhandlers[capability](layer)
                except NoMapToolConfigured:
                    utils.log("No map tool configured")
                    continue
                except ErrorInMapTool as error:
                    self.iface.messageBar().pushMessage("Error configuring map tool", error.message, level=QgsMessageBar.WARNING)
                    continue

    def showToolError(self, label, message):
        self.iface.messageBar().pushMessage(label, message, QgsMessageBar.WARNING)
            
    def openForm(self, layer, feature):
        if not layer.isEditable():
            layer.startEditing()

        self.band.setToGeometry(feature.geometry(), layer)
        self.dialogprovider.openDialog(feature=feature, layer=layer)
        self.band.reset()

    def addNewFeature(self, layer, geometry):
        fields = layer.pendingFields()
        
        feature = QgsFeature()
        feature.setGeometry( geometry )
        feature.initAttributes(fields.count())
        feature.setFields(fields)
        
        for indx in xrange(fields.count()):
            feature[indx] = layer.dataProvider().defaultValue(indx)

        self.openForm(layer, feature)

    def showOpenProjectDialog(self):
        """
        Show the project selection dialog.
        """
        self.stack.setCurrentIndex(1)
        self.infodock.hide()
        path = os.path.join(os.path.dirname(__file__), '..' , 'projects/')
        projects = getProjects(path, self.iface)
        projects = [project for project in projects if project.valid]
        self.projectwidget.loadProjectList(projects)
        
    def loadProject(self, project):
        """
        Load a project into QGIS.
        """
        utils.log(project)
        utils.log(project.name)
        utils.log(project.projectfile)
        utils.log(project.vaild)
        
        (passed, message) = project.onProjectLoad()
        
        if not passed:
            QMessageBox.warning(self.mainwindow, "Project Load Rejected", 
                                "Project couldn't be loaded because {}".format(message))
            return
        
        self.mapview.trigger()
        self.iface.newProject(False)        
        self.iface.mapCanvas().freeze()
        self.infodock.clearResults()
        # No idea why we have to set this each time.  Maybe QGIS deletes it for
        # some reason.
        self.badLayerHandler = BadLayerHandler(callback=self.missingLayers)
        QgsProject.instance().setBadLayerHandler( self.badLayerHandler )
        
        self.iface.messageBar().pushMessage("Project Loading","", QgsMessageBar.INFO)
        QApplication.processEvents()

        fileinfo = QFileInfo(project.projectfile)
        QgsProject.instance().read(fileinfo)

        self.iface.mapCanvas().updateScale()
        self.iface.mapCanvas().freeze(False)
        self.iface.mapCanvas().refresh()
        self.mainwindow.setWindowTitle("IntraMaps Roam: Mobile Data Collection")
        self.iface.projectRead.emit()
        
    def unload(self):
        del self.toolbar
        
    def connectSyncProviders(self, project):
        self.syncactionstoolbar.clear()
        
        syncactions = list(project.syncprovders())
        
        # Don't show the sync button if there is no sync providers
        if not syncactions:
            self.syncAction.setVisible(False)
            return
        
        self.syncAction.setVisible(True)
        
        for provider in syncactions:
            action = QAction(QIcon(":/icons/sync"), "Sync {}".format(provider.name), self.mainwindow)
            action.triggered.connect(functools.partial(self.syncProvider, provider))
            self.syncactionstoolbar.addAction(action)
        
        try:
            self.syncAction.toggled.disconnect()
        except TypeError:
            pass
        try:
            self.syncAction.triggered.disconnect()
        except TypeError:
            pass
        
        if len(syncactions) == 1:
            # If one provider is set then we just connect the main button.    
            self.syncAction.setCheckable(False)
            self.syncAction.setText("Sync")
            self.syncAction.triggered.connect(functools.partial(self.syncProvider, syncactions[0]))
        else:
            # the sync button because a sync menu
            self.syncAction.setCheckable(True)
            self.syncAction.setText("Sync Menu")
            showsyncoptions = (functools.partial(self.syncactionstoolbar.showToolbar, 
                                                 self.syncAction, None))
            self.syncAction.toggled.connect(showsyncoptions)

    def syncstarted(self):                   
        # Remove the old widget if it's still there.
        # I don't really like this. Seems hacky.
        try:
            self.iface.messageBar().popWidget(self.syncwidget)
        except RuntimeError:
            pass
        except AttributeError:
            pass
        
        self.iface.messageBar().findChildren(QToolButton)[0].setVisible(False)
        self.syncwidget = self.iface.messageBar().createMessage("Syncing", "Sync in progress", QIcon(":/icons/syncing"))
        button = QPushButton(self.syncwidget)
        button.setCheckable(True)
        button.setText("Status")
        button.setIcon(QIcon(":/icons/syncinfo"))
        button.toggled.connect(functools.partial(self.report.setVisible))
        pro = QProgressBar()
        pro.setMaximum(0)
        pro.setMinimum(0)
        self.syncwidget.layout().addWidget(pro)
        self.syncwidget.layout().addWidget(button)
        self.iface.messageBar().pushWidget(self.syncwidget, QgsMessageBar.INFO)
        
    def synccomplete(self):
        try:
            self.iface.messageBar().popWidget(self.syncwidget)
        except RuntimeError:
            pass
        
        stylesheet = ("QgsMessageBar { background-color: rgba(239, 255, 233); border: 0px solid #b9cfe4; } "
                     "QLabel,QTextEdit { color: #057f35; } ")
        
        closebutton = self.iface.messageBar().findChildren(QToolButton)[0]
        closebutton.setVisible(True)
        closebutton.clicked.connect(functools.partial(self.report.setVisible, False))
        self.syncwidget = self.iface.messageBar().createMessage("Syncing", "Sync Complete", QIcon(":/icons/syncdone"))
        button = QPushButton(self.syncwidget)
        button.setCheckable(True)
        button.setChecked(self.report.isVisible())
        button.setText("Sync Report")
        button.setIcon(QIcon(":/icons/syncinfo"))
        button.toggled.connect(functools.partial(self.report.setVisible))      
        pro = QProgressBar()
        pro.setMaximum(100)
        pro.setValue(100)
        self.syncwidget.layout().addWidget(pro)      
        self.syncwidget.layout().addWidget(button)
        self.iface.messageBar().pushWidget(self.syncwidget)
        self.iface.messageBar().setStyleSheet(stylesheet)
        self.iface.mapCanvas().refresh()
        
    def syncerror(self):
        try:
            self.iface.messageBar().popWidget(self.syncwidget)
        except RuntimeError:
            pass
        
        closebutton = self.iface.messageBar().findChildren(QToolButton)[0]
        closebutton.setVisible(True)
        closebutton.clicked.connect(functools.partial(self.report.setVisible, False))
        self.syncwidget = self.iface.messageBar().createMessage("Syncing", "Sync Error", QIcon(":/icons/syncfail"))
        button = QPushButton(self.syncwidget)
        button.setCheckable(True)
        button.setChecked(self.report.isVisible())
        button.setText("Sync Report")
        button.setIcon(QIcon(":/icons/syncinfo"))
        button.toggled.connect(functools.partial(self.report.setVisible))            
        self.syncwidget.layout().addWidget(button)
        self.iface.messageBar().pushWidget(self.syncwidget, QgsMessageBar.CRITICAL)
        self.iface.mapCanvas().refresh()
        
    def syncProvider(self, provider):
        self.syncAction.toggle()
        provider.syncStarted.connect(functools.partial(self.syncAction.setEnabled, False))
        provider.syncStarted.connect(self.syncstarted)
        
        provider.syncComplete.connect(self.synccomplete)
        provider.syncComplete.connect(functools.partial(self.syncAction.setEnabled, True))
        provider.syncComplete.connect(functools.partial(self.report.updateHTML))
        
        provider.syncMessage.connect(self.report.updateHTML)
        
        provider.syncError.connect(self.report.updateHTML)
        provider.syncError.connect(self.syncerror)
        provider.syncError.connect(functools.partial(self.syncAction.setEnabled, True))
        
        provider.startSync()
        
