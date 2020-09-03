"""A setuptools based setup module."""

import sys
from codecs import open
from os import path

from setuptools import find_packages, setup

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file.
with open(path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

requirements = [
    'ifaddr>=0.1.0',
    'pyee>=7.0.0',
    'jsonschema>=3.2.0',
    'tornado>=6.0.0',
    'zeroconf>=0.27.0',
]

setup(
    name='webthing',
    version='0.13.2',
    description='HTTP Web Thing implementation',
    long_description=long_description,
    url='https://github.com/mozilla-iot/webthing-python',
    author='Mozilla IoT',
    author_email='iot@mozilla.com',
    keywords='mozilla iot web thing webthing',
    packages=find_packages(exclude=['contrib', 'docs', 'tests']),
    install_requires=requirements,
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
    license='MPL-2.0',
    project_urls={
        'Source': 'https://github.com/mozilla-iot/webthing-python',
        'Tracker': 'https://github.com/mozilla-iot/webthing-python/issues',
    },
    python_requires='!=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*, <4',
)
