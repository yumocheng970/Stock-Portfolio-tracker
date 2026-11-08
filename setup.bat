@echo off
rem Setup for Windows (run it in the Miniforge Prompt): creates the conda environment
rem "spt" if it is missing, then runs the setup wizard (python -m setup) in it.
rem It does NOT install PostgreSQL or Miniforge (see README.md -> Quick start).
rem "call" is needed in front of conda: conda is itself a .bat file, and without
rem "call" this script would stop after the first conda command.
cd /d "%~dp0"

where conda >nul 2>nul
if errorlevel 1 (
    echo conda was not found. Install Miniforge first: https://github.com/conda-forge/miniforge
    echo Then open the "Miniforge Prompt" and run setup.bat again.
    exit /b 1
)

call conda env list | findstr /R /C:"^spt " >nul
if errorlevel 1 (
    echo Creating the conda environment "spt" from environment.yml, about a minute ...
    call conda env create -f environment.yml
    if errorlevel 1 exit /b 1
) else (
    echo The conda environment "spt" exists.
)

rem --no-capture-output: show the wizard's questions and let you type the answers
call conda run --no-capture-output -n spt python -m setup %*
exit /b %errorlevel%
