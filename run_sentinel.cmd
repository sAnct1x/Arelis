@echo off
pushd "%~dp0"
".venv\Scripts\python.exe" -m sentinel %*
popd
