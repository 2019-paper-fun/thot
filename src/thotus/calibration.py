import os
import sys
import json
import math
import pickle
from glob import glob
from collections import defaultdict

from thotus.ui import gui
from thotus.projection import CalibrationData, PointCloudGeneration, clean_model, fit_plane, fit_circle
from thotus.linedetect import LineMaker
from thotus.cloudify import cloudify
from thotus.ply import save_scene
from thotus.settings import save_data, load_data

import cv2
import numpy as np
from scipy.sparse import linalg

SKIP_CAM_CALIBRATION = 0

PATTERN_MATRIX_SIZE = (11, 6)
PATTERN_SQUARE_SIZE = 13.0
PATTERN_ORIGIN = 38.88 # distance plateau to second row of pattern
ESTIMATED_PLATFORM_TRANSLAT = [-5, 90, 320] # reference 

pattern_points = np.zeros((np.prod(PATTERN_MATRIX_SIZE), 3), np.float32)
pattern_points[:, :2] = np.indices(PATTERN_MATRIX_SIZE).T.reshape(-1, 2)

m_pattern_points = np.multiply(pattern_points, PATTERN_SQUARE_SIZE)

METADATA = defaultdict(lambda: {})

def _view_matrix(m):
    m = repr(m)[5:]
    m = m[1:1+m.rindex(']')]
    return str(eval(m))


def lasers_calibration(calibration_data, images):
    margin = int(len(images)/3)

    def compute_pc(X):
        # Load point cloud

        n = X.shape[0]
        Xm = X.sum(axis=0) / n
        M = np.array(X - Xm).T

        # Equivalent to:
#        U = numpy.linalg.svd(M)[0][:,2]
        # But 1200x times faster for large point clouds
        U = linalg.svds(M, k=2)[0]
        normal = np.cross(U.T[0], U.T[1])
        if normal[2] < 0:
            normal *= -1

        dist = np.dot(normal, Xm)
        std = np.dot(M.T, normal).std()
        return (dist, normal, std)

    images = images[margin:-margin]
    import random

    for laser in range(2):
        ranges = [ int(fn.rsplit('/')[-1].split('_')[1].split('.')[0]) for fn in  images]
        im = [METADATA[x] for x in images]

        assert len(ranges) == len(im)
        # TODO: use ROI for the pattern here

        obj = cloudify(calibration_data, './capture', [laser], ranges, pure_images=True, method='straightpureimage', camera=im, cylinder=(PATTERN_MATRIX_SIZE[1]*PATTERN_SQUARE_SIZE, 700)) # cylinder in mm

        tris = []
        v = [_ for _ in obj._mesh.vertexes if np.nonzero(_)[0].size]
        dist, normal, std = compute_pc(np.array(v))
        '''
        # Custom algo, RANSAC inspired
        for n in range(20): # take 20 random triangles
            tris.append( (
                random.choice(v),
                random.choice(v),
                random.choice(v)
                ))
        tris = np.array(tris)
#        tris = obj._mesh.vertexes
        normals = np.cross( tris[::,1 ] - tris[::,0]  , tris[::,2 ] - tris[::,0] ) # normals
        scores = []
        for n in normals:
            ref1 = random.choice(normals)
            ref2 = random.choice(normals)
            score = (np.linalg.norm(n - ref1) + np.linalg.norm(n-ref2))/2
            scores.append(score)

        best_idx = scores.index(min(scores))

        dist = np.mean(tris[best_idx][0]) # get average point of tri
        normal = normals[best_idx]

        dist = np.linalg.norm(dist)
        '''


        if laser == 0:
            name = 'left'
        else:
            name = 'right'

        calibration_data.laser_planes[laser].normal = normal
        calibration_data.laser_planes[laser].distance = dist
        print("laser %d:"%laser)
        print("Normal vector    %s"%(_view_matrix(normal)))
        print("Plane distance    %.4f mm"%(dist))

        save_scene("calibration_laser_%d.ply"%laser, obj)

def platform_calibration(calibration_data):
    x = []
    y = []
    z = []

    buggy_captures = set()

    pcg = PointCloudGeneration(calibration_data)
    for i, fn in enumerate(METADATA):
        gui.progress('Platform calibration', i, len(METADATA))
        corners = METADATA[fn]['chess_corners']
        try:
            ret, rvecs, tvecs = cv2.solvePnP(m_pattern_points, corners, calibration_data.camera_matrix, calibration_data.distortion_vector)
        except Exception as e:
            buggy_captures.add(fn)
            print("Error solving %s : %s"%(fn, e))
            ret = None
        if ret:
            pose = (cv2.Rodrigues(rvecs)[0], tvecs, corners)
            R = pose[0]
            t = pose[1].T[0]
            corner = pose[2]
            normal = R.T[2]
            distance = np.dot(normal, t)
            METADATA[fn]['plane'] = [distance, normal]
            if corners is not None:
                origin = corners[PATTERN_MATRIX_SIZE[0] * (PATTERN_MATRIX_SIZE[1] - 1)][0]
                origin = np.array([[origin[0]], [origin[1]]])
                t = pcg.compute_camera_point_cloud(origin, distance, normal)
                if t is not None:
                    x += [t[0][0]]
                    y += [t[1][0]]
                    z += [t[2][0]]

    print("\nBuggy Captures: %d"%len(buggy_captures))
    points = np.array(list(zip(x, y, z)))

    if points.size > 4:
        # Fitting a plane
        point, normal = fit_plane(points)
        if normal[1] > 0:
            normal = -normal
        # Fitting a circle inside the plane
        center, R, circle = fit_circle(point, normal, points)
        # Get real origin
        t = center - PATTERN_ORIGIN * np.array(normal)
        if t is not None:

            print("Platform calibration ")
            print(" Translation: " , _view_matrix(t))
            print(" Rotation: " , _view_matrix(R))
            if np.linalg.norm(t - ESTIMATED_PLATFORM_TRANSLAT) > 100:
                print("\n\n!!!!!!!! ISNOGOOD !! %s !~= %s"%(t, ESTIMATED_PLATFORM_TRANSLAT))

            calibration_data.platform_rotation = R
            calibration_data.platform_translation = t
    else:
        print(":((")
    return buggy_captures

def webcam_calibration(calibration_data, images):
    obj_points = []
    img_points = []
    found_nr = 0

    failed_serie = 0
    term = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 30, 0.001)

    for idx, fn in enumerate(images):
        gui.progress('Webcam calibration %s (%d found)... ' % (fn, found_nr), idx, len(images))
        img = cv2.imread(fn, 0)
        # rotation:
        img = cv2.flip(cv2.transpose(img), 1)

        if img is None:
            print("Failed to load", fn)
            continue

        w, h = img.shape[:2]

        found, corners = cv2.findChessboardCorners(img, PATTERN_MATRIX_SIZE, flags=cv2.CALIB_CB_NORMALIZE_IMAGE+cv2.CALIB_CB_FAST_CHECK)

        if not found:
            if found_nr > 20 and failed_serie > 10:
                break
            failed_serie += 1
            continue

        failed_serie = 0
        found_nr += 1
        cv2.cornerSubPix(img, corners, (11, 11), (-1, -1), term)

        METADATA[fn]['chess_corners'] = corners
        img_points.append(corners.reshape(-1, 2))
        obj_points.append(pattern_points.copy())

        # display
        vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        cv2.drawChessboardCorners(vis, PATTERN_MATRIX_SIZE, corners, found)
        gui.display(vis[int(vis.shape[0]/3):-100,], 'chess')

    print("\nComputing calibration...")
    if SKIP_CAM_CALIBRATION:
        calibration_data.camera_matrix = np.array([[1436.58142, 0.0, 488.061101], [0.0, 1425.6333, 646.008996], [0.0, 0.0, 1.0]])
        calibration_data.distortion_vector = np.array( [[-0.00563895863, -0.0672979095, -0.000632710648, -0.00155601109, 1.21223343]] )
        return

    rms, camera_matrix, dist_coefs, rvecs, tvecs = cv2.calibrateCamera(obj_points, img_points, (w, h), None, None)
    camera_matrix, roi = cv2.getOptimalNewCameraMatrix(camera_matrix, dist_coefs, (w, h), 1, (w,h))

    calibration_data.camera_matrix = camera_matrix
    calibration_data.distortion_vector = dist_coefs

    print("camera matrix:\n%s"% _view_matrix(camera_matrix))
    print("distortion coefficients: %s"% _view_matrix(dist_coefs))
    print("ROI: %s"%(repr(roi)))

def calibrate():

    calibration_data = CalibrationData()

    img_mask = './capture/color_*.png'
    img_names = sorted(glob(img_mask))

    webcam_calibration(calibration_data, img_names)
    buggy_captures = platform_calibration(calibration_data)

    good_images = set(METADATA)
    good_images.difference_update(buggy_captures)
    good_images = list(good_images)
    good_images.sort()
    pickle.dump(dict(
            images = good_images,
            metadata = dict(METADATA),
            )
            , open('images.js', 'wb'))

    lasers_calibration(calibration_data, good_images)
    save_data(calibration_data)
    METADATA.clear()
    gui.clear()

