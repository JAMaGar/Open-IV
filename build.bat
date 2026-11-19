@echo off
REM  Open-IV - gera o executavel unico (Windows 10/11)
cd /d "%~dp0"
echo [1/3] Instalando dependencias...
python -m pip install -r requirements.txt pyinstaller
echo [2/3] Testando o motor com o simulador...
python testes\teste_motor.py
if %ERRORLEVEL% NEQ 0 (
    echo  [ERRO] Os testes falharam. O executavel NAO foi gerado.
    pause
    exit /b 1
)
echo [3/3] Empacotando com PyInstaller...
python -m PyInstaller --noconfirm --onefile --windowed --name Open-IV ^
  --collect-data customtkinter --hidden-import=serial.tools.list_ports Open-IV.py
echo.
echo Executavel em: dist\Open-IV.exe
pause
