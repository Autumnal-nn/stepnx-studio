import sys

from setuptools import Extension, setup


setup(
    ext_modules=[
        Extension(
            "stepnx._mpeg_pcm",
            ["src/stepnx/_mpeg_pcm.c"],
            extra_compile_args=(
                ["/fp:strict"] if sys.platform == "win32"
                else ["-fno-fast-math", "-ffp-contract=off"]
            ),
        )
    ]
)
