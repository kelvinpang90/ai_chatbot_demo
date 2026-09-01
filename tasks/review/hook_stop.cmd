@echo off
REM Windows shim for the Stop hook.
REM
REM The hook command runs under cmd.exe, where a bare `bash` resolves to the WSL
REM launcher in WindowsApps -- a different filesystem, no access to this checkout
REM the way the rest of the tooling sees it. So resolve Git's own bash instead,
REM preferring the one that ships beside the git.exe already on PATH.
setlocal enabledelayedexpansion
set "PROJ=%~dp0..\.."
set "GITBASH="

for /f "delims=" %%G in ('where git 2^>nul') do (
  if not defined GITBASH if exist "%%~dpG..\bin\bash.exe" set "GITBASH=%%~dpG..\bin\bash.exe"
)
for %%B in (
  "%ProgramFiles%\Git\bin\bash.exe"
  "%ProgramW6432%\Git\bin\bash.exe"
  "%LOCALAPPDATA%\Programs\Git\bin\bash.exe"
) do (
  if not defined GITBASH if exist %%B set "GITBASH=%%~B"
)

if not defined GITBASH (
  echo [review-hook] Git Bash not found; review automation is off on this machine. 1>&2
  exit /b 0
)

"%GITBASH%" "%~dp0hook_stop.sh" "%PROJ%"
exit /b %errorlevel%
