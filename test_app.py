import os
import sys

# Adicionar pasta ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.database import init_db, get_db_connection
from backend.services import calculate_business_days, get_user_balances, detect_conflicts, get_dashboard_stats

def test_system():
    print("1. A inicializar base de dados...")
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as c FROM users")
    user_count = cursor.fetchone()["c"]
    print(f"   [OK] Colaboradores na BD: {user_count}")

    cursor.execute("SELECT COUNT(*) as c FROM holidays")
    holidays_count = cursor.fetchone()["c"]
    print(f"   [OK] Feriados registados: {holidays_count}")

    conn.close()

    print("\n2. A testar cálculo de dias úteis...")
    # 2026-04-20 (Segunda) a 2026-04-24 (Sexta) -> 5 dias úteis (sem feriados)
    days_1 = calculate_business_days("2026-04-20", "2026-04-24")
    print(f"   2026-04-20 a 2026-04-24: {days_1} dias úteis (esperado: 5)")
    assert days_1 == 5, f"Esperado 5, obtido {days_1}"

    # 2026-04-27 a 2026-05-01 (1 de Maio é feriado -> Segunda a Quinta = 4 dias)
    days_2 = calculate_business_days("2026-04-27", "2026-05-01")
    print(f"   2026-04-27 a 2026-05-01 (com Feriado 1 de Maio): {days_2} dias úteis (esperado: 4)")
    assert days_2 == 4, f"Esperado 4, obtido {days_2}"

    print("\n3. A testar saldos do colaborador...")
    balances = get_user_balances(3) # Ana Silva
    print(f"   Ana Silva -> Total: {balances['total_days']}, Aprovados: {balances['approved_days']}, Disponíveis: {balances['remaining_days']}")
    assert balances['total_days'] == 22

    print("\n4. A testar deteção de conflitos de férias...")
    # João Santos (id 4) e Ana Silva (id 3) são do mesmo departamento (Tecnologia, id 1)
    # Ana Silva já tem pedido aprovado em 2026-07-13 a 2026-07-24
    conflicts = detect_conflicts(4, "2026-07-15", "2026-07-20")
    print(f"   Conflitos detetados para João Santos em Julho: {len(conflicts)}")
    for c in conflicts:
        print(f"   - Sobreposição com: {c['user_name']} ({c['start_date']} a {c['end_date']})")
    assert len(conflicts) > 0, "Deveria detetar sobreposição com o pedido da Ana Silva"

    print("\n5. A testar estatísticas do Dashboard...")
    stats = get_dashboard_stats(2, "gestor", 1)
    print(f"   Colaboradores: {stats['total_users']}, Pendentes: {stats['pending_count']}")

    print("\n=======================================================")
    print("  TODOS OS TESTES DE VALIDAÇÃO PASSARAM COM SUCESSO! ")
    print("=======================================================")

if __name__ == "__main__":
    test_system()
