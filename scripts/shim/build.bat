@echo off
rem Build the Windows launcher shim.
rem
rem A .bat cannot forward arguments safely: cmd.exe re-parses "%*", so an
rem argument containing a space arrives split in two. This program receives
rem already-parsed argv and rebuilds the child command line itself.
rem
rem Run this only when shim.c changes; the result is committed as
rem envxx/data/envxx-shim.exe so users need no compiler.
call "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
cl /nologo /O1 /GS- shim.c shlwapi.lib
if errorlevel 1 exit /b 1
copy /y shim.exe ..\..\envxx\data\envxx-shim.exe >nul
echo built envxx/data/envxx-shim.exe
