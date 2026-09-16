from setuptools import setup

package_name = "demo_pkg"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    entry_points={
        "console_scripts": [
            "talker = demo_pkg.talker:main",
            "listener = demo_pkg.listener:main",
        ],
    },
)
