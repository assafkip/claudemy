@echo off
rem Double-click this file to start Book2Audio. Close this window to stop it.
title Book2Audio
set "HERE=%~dp0"
set "PATH=%HERE%ffmpeg;%PATH%"
"%HERE%python\python.exe" -m book2audio ui %*
if errorlevel 1 (
  echo.
  echo Book2Audio stopped with a problem. Is this folder inside a zip file? Unzip it first ^(right-click, Extract All^).
  pause
)
