@echo off
rem Builds morphbench.exe - the minimal native host, the entry point for Mod Organizer
rem 2 - with the stock .NET Framework compiler, which every Windows has. Nothing to install.
rem Outputs go to target/launcher, outside maintained source and Git.
rem The icon comes from morphbench.ico. make-icon.py draws it - it is a product as well, and
rem git keeps the script, not the binary: the history of an .ico shows only "file changed".
rem
rem ASCII only in this file, on purpose: cmd.exe reads a batch file in the console codepage,
rem and one stray byte makes it run fragments of lines. The line endings stay CRLF for the
rem same reason.
setlocal
set "BUILD_OUT=%~dp0..\target\launcher"
if exist "%~dp0..\..\..\src\main\release.py" set "BUILD_OUT=%~dp0..\..\..\target\launcher"
if not exist "%BUILD_OUT%" mkdir "%BUILD_OUT%"
rem The icon is a product of make-icon.py and is not in git. Draw it if it is not drawn yet.
if not exist "%BUILD_OUT%\morphbench.ico" (
    python "%~dp0make-icon.py" --out "%BUILD_OUT%\morphbench.ico" || (echo could not draw the icon & exit /b 3)
)
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo csc.exe of .NET Framework 4 not found: %CSC%
    exit /b 2
)
"%CSC%" /nologo /optimize+ /codepage:65001 /target:winexe /platform:anycpu ^
    /r:System.Windows.Forms.dll ^
    /win32manifest:"%~dp0morphbench.manifest" ^
    /win32icon:"%BUILD_OUT%\morphbench.ico" ^
    /out:"%BUILD_OUT%\morphbench.exe" "%~dp0morphbench.cs"
if errorlevel 1 exit /b %errorlevel%
echo built: %BUILD_OUT%\morphbench.exe
endlocal
