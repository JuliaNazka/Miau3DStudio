@echo off
call "D:\Miau3DStudio\tools\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
set "CUDA_HOME=D:\Miau3DStudio\tools\cuda\v12.6"
set "CUDA_PATH=%CUDA_HOME%"
set "PATH=%CUDA_HOME%\bin;%PATH%"
set DISTUTILS_USE_SDK=1
set TORCH_CUDA_ARCH_LIST=8.6
set MAX_JOBS=6
set "UV_CACHE_DIR=D:\Miau3DStudio\cache\uv"
where cl
nvcc --version | findstr release
uv pip install --python D:\Miau3DStudio\envs\miau\Scripts\python.exe --no-build-isolation -v "D:\Miau3DStudio\vendor\Hunyuan3D-2\hy3dgen\texgen\custom_rasterizer"
