"""
MODULE:    qambit
AUTHOR(S): Yann Chemin
PURPOSE:   QGIS plugin entry point.
SPDX-License-Identifier: Unlicense
"""


def classFactory(iface):
    from .plugin import QAmbitPlugin

    return QAmbitPlugin(iface)
