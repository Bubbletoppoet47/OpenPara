"""The wheel holds the compiled module next to the Python files, so it is a platform wheel (cp312-win_amd64), not a pure one."""
from setuptools import Distribution, setup


class BinaryDistribution(Distribution):
    def has_ext_modules(self):
        return True


setup(distclass=BinaryDistribution)
