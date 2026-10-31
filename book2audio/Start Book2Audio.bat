@echo off
rem Double-click this file to start Book2Audio. Closing this window stops it.
title Book2Audio
where book2audio >nul 2>nul && (book2audio ui %* & goto done)
py -c "import book2audio" >nul 2>nul && (py -m book2audio ui %* & goto done)
python -c "import book2audio" >nul 2>nul && (python -m book2audio ui %* & goto done)
echo.
echo Book2Audio is not installed yet.
echo Open README.md in this folder and follow the "Install" steps, then double-click this file again.
echo.
pause
exit /b 1
:done
if errorlevel 1 pause
