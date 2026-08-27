import subprocess
import threading
import time
import webbrowser
import os
import sys
import re

def start_server():
    import uvicorn
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, log_level="error")

def start_tunnel():
    time.sleep(1.5)
    print("\n" + "=" * 65)
    print("  🌐 A GERAR LINK PÚBLICO SEGURO (HTTPS) PARA TODA A EQUIPA...")
    print("=" * 65)

    # Iniciar túnel seguro via SSH (zero dependências / sem instalar nada)
    # Tenta localhost.run ou pinggy
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=30", "-R", "80:localhost:8000", "nokey@localhost.run"]
    
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        tunnel_url = None
        for line in proc.stdout:
            # Capturar o URL gerado pelo túnel
            match = re.search(r'https://[a-zA-Z0-9\.\-_]+\.lhr\.life|https://[a-zA-Z0-9\.\-_]+', line)
            if match and not tunnel_url:
                tunnel_url = match.group(0)
                print("\n" + "⭐" * 30)
                print(f"  👉 LINK PÚBLICO PARA ENVIAR À EQUIPA:")
                print(f"     {tunnel_url}")
                print("⭐" * 30 + "\n")
                print("  Os colaboradores podem aceder neste link a partir de:")
                print("  • Qualquer computador (em casa, remoto, etc.)")
                print("  • Telemóveis (4G, 5G, Wi-Fi de casa)")
                print("  • Sem estarem na mesma rede!")
                print("=" * 65)
                print("  Mantenha esta janela aberta enquanto a equipa estiver a usar.\n")
                webbrowser.open(tunnel_url)
                break
    except Exception as e:
        print(f"  Nota: Para gerar link público manual use: ssh -R 80:localhost:8000 localhost.run")

if __name__ == "__main__":
    print("=" * 65)
    print("  🌴 TeamVacay - Acesso Global Online para a Equipa")
    print("=" * 65)
    print("  A iniciar servidor local e túnel público...")

    # Thread do servidor local
    t_server = threading.Thread(target=start_server, daemon=True)
    t_server.start()

    # Iniciar túnel público
    start_tunnel()

    # Manter em execução
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
