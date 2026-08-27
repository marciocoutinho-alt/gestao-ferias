@echo off
title TeamVacay - Gestao de Ferias
echo =======================================================
echo    Iniciando TeamVacay - Gestao de Ferias da Equipa
echo =======================================================
python -m pip install fastapi uvicorn jinja2 python-multipart --quiet
python main.py
pause
