"""Small differences between pyvista versions (older ones do not accept extract_surface(algorithm=None))."""
import pyvista as pv


def _extract_surface_compat(self):
    try:
        return self.extract_surface(algorithm=None)
    except TypeError:
        return self.extract_surface()


pv.DataSet.extract_surface_compat = _extract_surface_compat


def cell_quality(grid, measure="scaled_jacobian"):
    """Per-cell quality as an array, for old and new pyvista."""
    import numpy as np
    if hasattr(grid, "cell_quality"):
        return np.asarray(grid.cell_quality(measure)[measure])
    return np.asarray(grid.compute_cell_quality(quality_measure=measure)["CellQuality"])
