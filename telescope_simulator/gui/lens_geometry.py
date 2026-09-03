"""Pure Qt-geometry helper shared by `OpticItem` (canvas rendering) and the
"Add optic" dialog's live construction-diagram preview, so both draw a
lens's true spherical-sag silhouette from one implementation instead of two
copies that could drift apart."""
from __future__ import annotations

import numpy as np
from pyqtgraph.Qt import QtCore, QtGui

from ..model.optics import Optic, surface_sag


def build_lens_polygon(optic: Optic, n_samples: int = 48) -> QtGui.QPolygonF:
    """Closed outline of `optic`'s cross-section in its own local,
    unrotated/untranslated (z, x) frame -- front surface vertex at local
    z=0, back surface vertex at local z=`optic.thickness_center`."""
    half_d = max(optic.diameter_full, 1e-6) / 2.0
    xs = np.linspace(-half_d, half_d, n_samples)
    front = np.array([surface_sag(optic.r1, x) for x in xs])
    back = optic.thickness_center + np.array([surface_sag(optic.r2, x) for x in xs])

    pts = [QtCore.QPointF(float(z), float(x)) for z, x in zip(front, xs)]
    pts += [QtCore.QPointF(float(z), float(x)) for z, x in zip(back[::-1], xs[::-1])]
    return QtGui.QPolygonF(pts)
