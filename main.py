import uvicorn
import webbrowser
import os
import sys
import threading
import time
import socket

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def open_browser():
    time.sleep(1.2)
    webbrowser.open("http://localhost:8000")

if __name__ == "__main__":
    local_ip = get_local_ip()
    print("=" * 65)
    print("  🌴 TeamVacay - Sistema de Gestão de Férias da Equipa")
    print("=" * 65)
    print(f"  💻 Acesso Local (Neste Computador):  http://localhost:8000")
    print(f"  📱 Acesso na Rede da Equipa (Wi-Fi): http://{local_ip}:8000")
    print("=" * 65)
    print("  Credenciais predefinidas de teste:")
    print("  • Administrador / RH : sofia.rh@empresa.pt     (palavra-passe: 1234)")
    print("  • Gestor de TI       : carlos.mendes@empresa.pt (palavra-passe: 1234)")
    print("  • Colaborador        : ana.silva@empresa.pt     (palavra-passe: 1234)")
    print("=" * 65)

    # Abrir navegador automaticamente
    threading.Thread(target=open_browser, daemon=True).start()

    # Iniciar servidor Uvicorn acessível na rede local
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
