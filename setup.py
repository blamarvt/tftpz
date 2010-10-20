from setuptools import setup

setup(
		name="tftpz",
		version="0.2",
		author="Brian Lamar",
		author_email="brian.lamar@rackspace.com",
		maintainer="Nicholas VonHollen",
		maintainer_email="nicholas.vonhollen@rackspace.com",
		license="Apache License 2.0",
		packages=['tftpz'],
		package_dir={"":"src/py"},
		data_files=[('/etc/init.d', ['src/init.d/tftpz'])],
		entry_points="""
		[console_scripts]
                tftpz=tftpz:main
		"""
		)
