# -*- coding: utf-8 -*-

import os
import re

from setuptools import setup, find_packages


def _get_version():
    v_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'ecache', '__init__.py')
    ver_info_str = re.compile(r".*version_info = \((.*?)\)", re.S). \
        match(open(v_file_path).read()).group(1)
    return re.sub(r'(\'|"|\s+)', '', ver_info_str).replace(',', '.')

with open("README.rst") as f:
    long_description = f.read()

requires = []

with open("requirements.txt") as f:
    for line in f:
        requires.append(line)


setup(
    name="ecache",
    version=_get_version(),
    description="Cache integration with sqlalchemy.",
    long_description=long_description,
    author='Mrkiven',
    author_email="kiven.mr@gmail.com",
    package=find_packages(),
    license='MIT',
    install_requires=requires
)
