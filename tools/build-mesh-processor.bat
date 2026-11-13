@echo off
call "D:\Miau3DStudio\tools\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
set DISTUTILS_USE_SDK=1
cd /d "D:\Miau3DStudio\vendor\Hunyuan3D-2\hy3dgen\texgen\differentiable_renderer"
"D:\Miau3DStudio\envs\miau\Scripts\python.exe" setup.py build_ext --inplace
dir /b *.pyd
