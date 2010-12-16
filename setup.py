#!/usr/bin/python
from setuptools import setup

setup(
    name             = "tftpz",
    version          = "0.3",
    author           = "Brian Lamar",
    author_email     = "brian.lamar@rackspace.com",
    maintainer       = "Nicholas VonHollen",
    maintainer_email = "nicholas.vonhollen@rackspace.com",
    license          = "Apache License 2.0",
    packages         = ['tftpz'],
    package_dir      = {"":"src/py"},
)
