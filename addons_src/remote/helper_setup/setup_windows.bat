@echo off
rem OpenPara Remote helper - set-up for Windows.
rem Finds Python 3.8 or newer, installs it first when this computer has none, then runs the helper's own set-up
rem (it shows the ACCESS CODE and makes the helper start with every login).
rem   Set up (Windows).bat           asks before it installs anything
rem   Set up (Windows).bat --yes     does not ask
rem Only plain ASCII and no brackets inside echo lines that sit in a block: this file is read by cmd.exe, which is picky.
setlocal EnableExtensions
title OpenPara Remote helper - set-up
cd /d "%~dp0"

set "ASSUME_YES=0"
if /i "%~1"=="--yes" set "ASSUME_YES=1"
set "RC=1"

if not exist "openpara_remote_helper.py" goto nohelper

call :findpython
if defined PYEXE goto run

echo Python 3.8 or newer was not found on this computer.
echo.
where powershell >nul 2>nul
if errorlevel 1 goto nopowershell

rem Which Python to fetch: the 64-bit one, the ARM one or the 32-bit one.
set "ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "ARCH=%PROCESSOR_ARCHITEW6432%"
set "PYFILE=python-3.12.10-amd64.exe"
if /i "%ARCH%"=="ARM64" set "PYFILE=python-3.12.10-arm64.exe"
if /i "%ARCH%"=="x86" set "PYFILE=python-3.12.10.exe"
set "PYURL=https://www.python.org/ftp/python/3.12.10/%PYFILE%"
set "PYDL=%TEMP%\%PYFILE%"

echo OpenPara can install Python 3.12 for you: it downloads the installer from python.org
echo (about 25 MB), checks that it is signed by the Python Software Foundation, and installs
echo it for your user account only. That needs no administrator password.
echo.
if "%ASSUME_YES%"=="1" goto download
choice /c YN /m "Install Python now"
if errorlevel 2 goto declined

:download
echo.
echo Downloading %PYURL%
if exist "%PYDL%" del "%PYDL%" >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile($env:PYURL, $env:PYDL)"
if errorlevel 1 goto nodownload
if not exist "%PYDL%" goto nodownload

powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = Get-AuthenticodeSignature -LiteralPath $env:PYDL; if ($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -like '*Python Software Foundation*') { exit 0 } else { exit 1 }"
if errorlevel 1 goto badsignature

echo Installing Python. This takes a minute or two.
start "" /wait "%PYDL%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_test=0 Include_doc=0 Shortcuts=0
set "INSTALL_RC=%errorlevel%"
del "%PYDL%" >nul 2>nul

call :findpython
if not defined PYEXE goto installfailed
echo Python is installed.
echo.

:run
echo Using %PYEXE%
echo.
"%PYEXE%" openpara_remote_helper.py --install
set "RC=%errorlevel%"
echo.
if "%RC%"=="0" echo Write the ACCESS CODE down. It is shown once. Then restart this computer.
if not "%RC%"=="0" echo The helper's own set-up reported a problem, code %RC%. What it wrote above says what.
goto end

:nohelper
echo openpara_remote_helper.py is not in this folder.
echo Copy the whole "OpenPara Remote helper" folder to this computer, then run this again.
goto end

:nopowershell
echo This computer has no PowerShell, which the download needs.
echo Install Python 3.8 or newer by hand from https://www.python.org/downloads/ and run this again.
goto end

:declined
echo.
echo Python was not installed, so the helper was not set up.
goto end

:nodownload
echo.
echo The download did not work. Is this computer online?
echo Try again, or install Python 3.8 or newer by hand from https://www.python.org/downloads/
echo and run this again.
del "%PYDL%" >nul 2>nul
goto end

:badsignature
echo.
echo The downloaded file is not signed by the Python Software Foundation, so it was not run.
echo Install Python 3.8 or newer by hand from https://www.python.org/downloads/ and run this again.
del "%PYDL%" >nul 2>nul
goto end

:installfailed
echo.
echo The Python installer ended with code %INSTALL_RC%, and Python 3.8 or newer is still not found.
echo This needs Windows 10 or newer. Install Python by hand from https://www.python.org/downloads/
echo and run this again.
goto end

:end
echo.
if "%ASSUME_YES%"=="0" pause
exit /b %RC%

rem ---- Sets PYEXE to the full path of the first Python 3.8 or newer on this computer.
:findpython
set "PYEXE="
call :try "py -3"
call :try "python"
call :try "python3"
rem Where the installer above puts it: this window does not see the new PATH yet.
for %%V in (313 312 311 310 39 38) do call :tryfile "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
for %%V in (313 312 311 310 39 38) do call :tryfile "%ProgramFiles%\Python%%V\python.exe"
if defined ProgramW6432 for %%V in (313 312 311 310 39 38) do call :tryfile "%ProgramW6432%\Python%%V\python.exe"
exit /b 0

:try
if defined PYEXE exit /b 0
%~1 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
for /f "delims=" %%P in ('%~1 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
exit /b 0

:tryfile
if defined PYEXE exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PYEXE=%~1"
exit /b 0
