#!/usr/bin/env python
# coding=utf-8
"""
python distribute file
"""

from __future__ import (absolute_import, division, print_function,
                        unicode_literals, with_statement)
import os
import pkg_resources

from setuptools import setup, find_packages

setup(
    name="aiom3u8downloader",
    version='1.1.4',
    description=
    "Update package m3u8downloader to use aiohttp download m3u8 url",
    long_description=open('README.rst').read(),
    long_description_content_type='text/x-rst',
    python_requires=">=3.6",
    install_requires=[
        'requests>=2.25.1',
        'aiohttp>=3.8.1'
    ],
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'aiodownloadm3u8 = aiom3u8downloader.aiodownloadm3u8:main',
        ]
    },
    package_dir={'':"."},
    packages=find_packages(),
    package_data={'aiom3u8downloader': ['logger.conf']},
    author="cghn",
    license="GPLv3",
    url="https://github.com/kirikumo/aiom3u8downloader/",
    classifiers=[
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Programming Language :: Python :: 3.6',
    ])
