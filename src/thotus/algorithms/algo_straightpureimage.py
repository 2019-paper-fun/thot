from .algo_pureimage import compute as pure_compute

def compute(img, laser_nr):
    return pure_compute(img, laser_nr, 30, use_ransac=True)
