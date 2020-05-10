from setuptools import setup, find_packages


setup(
    name="sbt-client-py",
    version="0.1.0",
    description="Thin async client for sbt (scala build tool)",
    author="Andrei Ivanchenko",
    url="https://github.com/anivanch/sbt-client-py",
    packages=find_packages(exclude=("tests", "tests.*")),
    install_requires=["pydantic"],
    python_requires=">=3.8",
)
