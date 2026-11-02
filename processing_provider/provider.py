"""
MODULE:    qambit.processing_provider.provider
AUTHOR(S): Yann Chemin
PURPOSE:   QAmbit tools in the Processing toolbox, for models and batch runs:
           importing openambit logs and downloading terrain (IGN LiDAR HD or
           Copernicus DEM) around a box.
SPDX-License-Identifier: Unlicense
"""

import os

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterRasterDestination,
    QgsProcessingProvider,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon

from .. import settings
from ..core import dem, lidarhd, store
from ..core.logparser import find_logs

ICON = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons", "icon.svg")


def translate(context, text):
    return QCoreApplication.translate(context, text)


class _Algorithm(QgsProcessingAlgorithm):
    def tr(self, text):
        return translate("QAmbit", text)

    def createInstance(self):
        return type(self)()

    def icon(self):
        return QIcon(ICON)

    def group(self):
        return translate("QAmbit", "Suunto Ambit")

    def groupId(self):
        return "ambit"


class ImportLogsAlgorithm(_Algorithm):
    FOLDER, GPKG, FORCE, IMPORTED = "FOLDER", "GPKG", "FORCE", "IMPORTED"

    def name(self):
        return "importlogs"

    def displayName(self):
        return translate("QAmbit", "Import openambit logs")

    def shortHelpString(self):
        return translate(
            "QAmbit",
            "Reads the openambit log files (log_*.log) of a folder into a GeoPackage of tracks "
            "(LineStringZM: altitude, seconds), position fixes with their sensor values, and laps. "
            "Logs that did not change since the last import are skipped.",
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.FOLDER,
                translate("QAmbit", "openambit folder"),
                QgsProcessingParameterFile.Behavior.Folder,
                defaultValue=settings.value("data_dir"),
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.GPKG,
                translate("QAmbit", "Move store"),
                "GeoPackage (*.gpkg)",
                settings.value("gpkg"),
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.FORCE, translate("QAmbit", "Re-import unchanged logs"), False
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(self.IMPORTED, translate("QAmbit", "Imported moves"))
        )

    def processAlgorithm(self, parameters, context, feedback):
        folder = self.parameterAsFile(parameters, self.FOLDER, context)
        gpkg = self.parameterAsFileOutput(parameters, self.GPKG, context)
        paths = find_logs(folder)
        if not paths:
            raise QgsProcessingException(
                translate("QAmbit", "No openambit log in {}.").format(folder)
            )

        def progress(done, total, log_id):
            feedback.setProgress(100.0 * done / max(total, 1))

        result = store.import_logs(
            paths,
            gpkg,
            progress,
            feedback.isCanceled,
            self.parameterAsBoolean(parameters, self.FORCE, context),
        )
        for log_id, reason in result["skipped"]:
            feedback.pushInfo("{}: {}".format(log_id, reason))
        feedback.pushInfo(
            translate("QAmbit", "{} imported, {} unchanged, {} skipped.").format(
                len(result["imported"]),
                len(result["unchanged"]),
                len(result["skipped"]),
            )
        )
        return {self.GPKG: gpkg, self.IMPORTED: len(result["imported"])}


class TerrainAlgorithm(_Algorithm):
    EXTENT, SOURCE, PRODUCT, OUTPUT = "EXTENT", "SOURCE", "PRODUCT", "OUTPUT"
    SOURCES = ("auto", "lidarhd", "copernicus")
    PRODUCTS = ("mns", "mnt")

    def name(self):
        return "downloadterrain"

    def displayName(self):
        return translate("QAmbit", "Download terrain (IGN LiDAR HD / Copernicus DEM)")

    def shortHelpString(self):
        return translate(
            "QAmbit",
            "Downloads the elevation of an extent. IGN LiDAR HD covers metropolitan France at "
            "50 cm (surface model MNS or terrain model MNT); the resolution is coarsened for large "
            "extents. The Copernicus DEM (30 m, or 90 m above one degree) covers the world. "
            "Automatic uses LiDAR HD where it covers the extent.",
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterExtent(self.EXTENT, translate("QAmbit", "Extent")))
        self.addParameter(
            QgsProcessingParameterEnum(
                self.SOURCE,
                translate("QAmbit", "Source"),
                [
                    translate("QAmbit", "Automatic"),
                    translate("QAmbit", "IGN LiDAR HD"),
                    translate("QAmbit", "Copernicus DEM"),
                ],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PRODUCT,
                translate("QAmbit", "LiDAR HD model"),
                [
                    translate("QAmbit", "Surface (MNS)"),
                    translate("QAmbit", "Terrain (MNT)"),
                ],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(self.OUTPUT, translate("QAmbit", "Terrain"))
        )

    def processAlgorithm(self, parameters, context, feedback):
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        # Given a CRS, parameterAsExtent reprojects the extent to it.
        rect = self.parameterAsExtent(parameters, self.EXTENT, context, wgs84)
        box = (rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())
        source = self.SOURCES[self.parameterAsEnum(parameters, self.SOURCE, context)]
        product = self.PRODUCTS[self.parameterAsEnum(parameters, self.PRODUCT, context)]
        output = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        cache = settings.value("dem_cache")

        def progress(done, total, what):
            feedback.setProgress(100.0 * done / max(total, 1))
            if what:
                feedback.setProgressText(what)

        path = None
        try:
            if source in ("auto", "lidarhd"):
                try:
                    path = lidarhd.build_lidarhd_dem(
                        *box,
                        cache,
                        product=product,
                        feedback=progress,
                        is_canceled=feedback.isCanceled,
                    )
                except (lidarhd.NotCovered, ValueError) as e:
                    if source == "lidarhd":
                        raise
                    feedback.pushInfo(translate("QAmbit", "LiDAR HD not used: {}").format(e))
            if path is None:
                path = dem.build_copernicus_dem(*box, cache, feedback=progress)
        except (ValueError, OSError, RuntimeError) as e:
            raise QgsProcessingException(str(e)) from e

        from osgeo import gdal

        gdal.UseExceptions()
        gdal.Translate(output, path, creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
        return {self.OUTPUT: output}


class QAmbitProvider(QgsProcessingProvider):
    def id(self):
        return "qambit"

    def name(self):
        return "QAmbit"

    def icon(self):
        return QIcon(ICON)

    def loadAlgorithms(self):
        self.addAlgorithm(ImportLogsAlgorithm())
        self.addAlgorithm(TerrainAlgorithm())
