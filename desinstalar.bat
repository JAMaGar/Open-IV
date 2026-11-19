@echo off
chcp 65001 >nul
title Open-IV - Desinstalador
set "INSTALL_DIR=%LOCALAPPDATA%\Open-IV"
set "DESKTOP="
for /f "skip=2 tokens=1,2*" %%A in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders" /v Desktop 2^>nul') do call set "DESKTOP=%%C"
if not defined DESKTOP if exist "%USERPROFILE%\Desktop" set "DESKTOP=%USERPROFILE%\Desktop"
echo.
echo  Vai remover o programa em %INSTALL_DIR% e o atalho da Area de Trabalho.
echo  Os DADOS medidos e a configuracao (%APPDATA%\Open-IV) NAO sao apagados.
set /p "OK=  Confirmar (S/N): "
if /i not "%OK%"=="S" exit /b 0
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
if defined DESKTOP if exist "%DESKTOP%\Open-IV.vbs" del "%DESKTOP%\Open-IV.vbs"
echo  Feito.
pause
