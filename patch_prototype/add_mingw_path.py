"""Prepend PlatformIO's bundled MinGW toolchain to PATH for the native env.

The `native` platform expects gcc/g++ on PATH but does not add the
`platformio/toolchain-gccmingw32` package to it automatically on Windows.
"""
import os

Import("env")

pkg_dir = env.PioPlatform().get_package_dir("toolchain-gccmingw32")
if pkg_dir:
    env.PrependENVPath("PATH", os.path.join(pkg_dir, "bin"))

# Static-link the MinGW runtime so the test exe runs without the
# toolchain's DLLs (libgcc_s_dw2-1.dll etc.) on the system PATH.
env.Append(LINKFLAGS=["-static", "-static-libgcc", "-static-libstdc++"])
