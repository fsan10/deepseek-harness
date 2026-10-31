"""Package the self-contained folder without including runtime or test data."""
from pathlib import Path
from setuptools import find_packages, setup

ROOT = Path(__file__).resolve().parent
subpackages = find_packages(str(ROOT), exclude=("tests", "tests.*", "tools", "tools.*"))
setup(packages=["commerce_api"] + ["commerce_api." + package for package in subpackages],
      package_dir={"commerce_api": "."}, include_package_data=False)
