import pickle

from thotus import model
from thotus.algorithms.projection import PointCloudGeneration

import numpy as np

def meshify(calibration_data, lines=None, camera=False, lasers=range(2), cylinder=(1000, 1000)):
    pcg = PointCloudGeneration(calibration_data)
    if not lines:
        lines = pickle.load(open('lines2d.pyk', 'rb+'))

    obj = Mesh()
    computer = pcg.compute_camera_point_cloud if camera else pcg.compute_point_cloud
    for angle, l in lines.items():
        for laser in lasers:
            x = l[laser]
            if x:
                pc = computer(*x)
                if pc is not None:
                    obj.append_point(pc, radius=cylinder[0], height=cylinder[1])
    return obj.get()

class Mesh:
    def __init__(self):
        self.obj = model.Model(None, is_point_cloud=True)
        self.obj._add_mesh()
        self.obj._mesh._prepare_vertex_count(4000000)

    def get(self):
        return self.obj

    def append_point(self, point, radius=100, height=100):
        color = (50, 180, 180)  # TODO: :(
        obj = self.obj
        rho = np.abs(np.sqrt(np.square(point[0, :]) + np.square(point[1, :])))
        z = point[2, :]

        idx = np.where((z >= 0) &
                       (z <= height) &
                       (rho < radius))[0]

        for i in idx:
            obj._mesh._add_vertex(
                point[0][i], point[1][i], point[2][i],
                color[0], color[1], color[2])
        # Compute Z center
        if point.shape[1] > 0:
            zmax = max(point[2])
            if zmax > obj._size[2]:
                obj._size[2] = zmax
