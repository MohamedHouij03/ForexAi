@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0py.ps1" training.walk_forward %*
