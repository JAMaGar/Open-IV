@echo off
chcp 65001 >nul
title Open-IV - Instalador
echo.
echo  Open-IV 1.0 - Instalador (ambiente Python local, sem internet apos as dependencias)
echo  =================================================================================
echo.
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  [ERRO] Python nao encontrado. Instale Python 3.10+ e marque "Add Python to PATH".
    pause
    exit /b 1
)
set "INSTALL_DIR=%LOCALAPPDATA%\Open-IV"
echo  Instalando em: %INSTALL_DIR%
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo  [1/5] Copiando arquivos...
copy /Y "%~dp0Open-IV.py" "%INSTALL_DIR%\" >nul
copy /Y "%~dp0requirements.txt" "%INSTALL_DIR%\" >nul
xcopy /E /I /Y /Q "%~dp0open_iv" "%INSTALL_DIR%\open_iv" >nul
xcopy /E /I /Y /Q "%~dp0testes" "%INSTALL_DIR%\testes" >nul

echo  [2/5] Criando ambiente virtual...
if not exist "%INSTALL_DIR%\venv\Scripts\python.exe" python -m venv "%INSTALL_DIR%\venv"
if %ERRORLEVEL% NEQ 0 (
    echo  [ERRO] Falha ao criar o ambiente virtual.
    pause
    exit /b 1
)

echo  [3/5] Instalando dependencias (1-3 min)...
"%INSTALL_DIR%\venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
"%INSTALL_DIR%\venv\Scripts\python.exe" -m pip install -r "%INSTALL_DIR%\requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo  [ERRO] Falha ao instalar as dependencias.
    pause
    exit /b 1
)

echo  [4/5] Testando com o simulador...
"%INSTALL_DIR%\venv\Scripts\python.exe" "%INSTALL_DIR%\testes\teste_motor.py" >"%INSTALL_DIR%\teste_instalacao.txt" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  [AVISO] O autoteste falhou; veja %INSTALL_DIR%\teste_instalacao.txt
) else (
    echo        Autoteste OK.
)

echo  [5/5] Criando atalhos...
set "VBS=%INSTALL_DIR%\Open-IV.vbs"
> "%VBS%" echo Set WshShell = CreateObject("WScript.Shell")
>> "%VBS%" echo WshShell.Run """%INSTALL_DIR%\venv\Scripts\pythonw.exe"" ""%INSTALL_DIR%\Open-IV.py""", 0, False
set "VBS2=%INSTALL_DIR%\Open-IV (simulador).vbs"
> "%VBS2%" echo Set WshShell = CreateObject("WScript.Shell")
>> "%VBS2%" echo WshShell.Run """%INSTALL_DIR%\venv\Scripts\pythonw.exe"" ""%INSTALL_DIR%\Open-IV.py"" --simular mis", 0, False

set "DESKTOP="
for /f "skip=2 tokens=1,2*" %%A in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders" /v Desktop 2^>nul') do call set "DESKTOP=%%C"
if not defined DESKTOP if exist "%USERPROFILE%\Desktop" set "DESKTOP=%USERPROFILE%\Desktop"
if not defined DESKTOP if exist "%USERPROFILE%\OneDrive\Desktop" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"
if defined DESKTOP (
    copy /Y "%VBS%" "%DESKTOP%\Open-IV.vbs" >nul 2>nul
    echo        Atalho criado em %DESKTOP%
) else (
    echo        Crie um atalho para: %VBS%
)
echo.
echo  INSTALACAO CONCLUIDA. Para treinar sem o instrumento: "%VBS2%"
echo  O MemristorProbe antigo NAO foi alterado nem removido.
echo.
pause
