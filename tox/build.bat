@echo off
rem Reproducible build of c-toxcore v0.2.23 (text-only, shared) for x64 Windows / MSVC.
rem Prereqs: vcpkg cloned+bootstrapped in .\vcpkg and
rem   vcpkg install libsodium pthreads pkgconf --triplet x64-windows
setlocal
set ROOT=%~dp0
for /f "usebackq delims=" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set VSDIR=%%i
call "%VSDIR%\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
set VCPKG=%ROOT%vcpkg
cmake -S "%ROOT%c-toxcore" -B "%ROOT%build" -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_TOOLCHAIN_FILE="%VCPKG%\scripts\buildsystems\vcpkg.cmake" ^
  -DVCPKG_TARGET_TRIPLET=x64-windows -DVCPKG_MANIFEST_MODE=OFF ^
  -DPKG_CONFIG_EXECUTABLE="%VCPKG%\installed\x64-windows\tools\pkgconf\pkgconf.exe" ^
  -DENABLE_SHARED=ON -DENABLE_STATIC=OFF ^
  -DCMAKE_WINDOWS_EXPORT_ALL_SYMBOLS=ON ^
  -DBUILD_TOXAV=OFF -DDHT_BOOTSTRAP=OFF -DBOOTSTRAP_DAEMON=OFF ^
  -DUNITTEST=OFF -DAUTOTEST=OFF -DBUILD_FUN_UTILS=OFF -DBUILD_MISC_TESTS=OFF || exit /b 1
cmake --build "%ROOT%build" --target toxcore_shared || exit /b 1
if not exist "%ROOT%bin" mkdir "%ROOT%bin"
for /r "%ROOT%build" %%f in (toxcore.dll) do if exist "%%f" copy /y "%%f" "%ROOT%bin\" >nul
copy /y "%VCPKG%\installed\x64-windows\bin\libsodium.dll" "%ROOT%bin\" >nul
copy /y "%VCPKG%\installed\x64-windows\bin\pthreadVC3.dll" "%ROOT%bin\" >nul
echo BUILD OK
