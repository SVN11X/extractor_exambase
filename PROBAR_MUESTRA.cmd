@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 goto usar_py
where python >nul 2>nul
if not errorlevel 1 goto usar_python
echo Necesitas Python 3.10 o posterior.
pause
exit /b 1
:usar_py
py -3 extractor.py --input entrada_muestra --output prueba_local --ocr off --zip
goto terminar
:usar_python
python extractor.py --input entrada_muestra --output prueba_local --ocr off --zip
:terminar
echo.
echo Esta muestra contiene SOLO la pagina 1: 5 de 349 preguntas.
echo El codigo de salida 2 indica cobertura parcial esperada.
pause
