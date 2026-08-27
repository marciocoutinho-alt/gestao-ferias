# 🌴 TeamVacay - Gestão de Férias da Equipa

Aplicação web completa, moderna e autónoma para gestão de férias, ausências, aprovações por equipa, saldos e calendário com deteção inteligente de conflitos.

---

## 🚀 Como Iniciar a Aplicação

### Opção 1: Duplo clique (Mais simples)
Execute o ficheiro **`iniciar.bat`** na pasta do projeto.

### Opção 2: Linha de comandos
Abra o terminal na pasta do projeto e execute:
```bash
python main.py
```

Aceda no seu navegador ao endereço: **`http://127.0.0.1:8000`**

---

## 👥 Papéis e Níveis de Acesso (Roles)

A aplicação inclui um seletor de utilizadores e papéis no topo direito para testar os diferentes perfis instantaneamente:

### 1. Colaborador / Funcionário (Auto-serviço)
* **Novo Pedido**: Submissão de pedidos com cálculo automático de dias úteis (descontando fins de semana e feriados nacionais).
* **Gestão de Saldo**: Acompanhamento dos dias anuais, gozados, pendentes e disponíveis.
* **Histórico**: Acompanhar o estado de aprovação (*Pendente*, *Aprovado*, *Rejeitado*) e cancelamento de pedidos pendentes.
* **Calendário & Gantt**: Consulta de mapa da equipa para verificar ausências dos colegas.

### 2. Gestor de Equipa / Team Lead
* Todas as permissões de colaborador.
* **Fila de Aprovações**: Aprovar ou rejeitar pedidos dos membros do seu departamento.
* **Deteção de Conflitos Inteligente**: Alerta visual automático quando 2 ou mais pessoas do mesmo departamento pedem férias no mesmo período.
* **Visão Gantt / Linha do Tempo**: Visualização diária de quem está presente e ausente na equipa.

### 3. Administrador / Recursos Humanos (RH)
* Todas as permissões anteriores com visão global da empresa.
* **Gestão da Equipa**: Criar novos colaboradores, alterar departamentos e ajustar limites de dias anuais de férias.
* **Feriados e Pontes**: Gestão de feriados nacionais e pontes com reflexo imediato no cálculo de dias úteis.
* **Exportação**: Download do mapa de férias em **Excel/CSV** e sincronização de calendário com **Outlook / Google Calendar (iCal)**.

---

## 🛠️ Tecnologias Utilizadas

* **Backend**: Python (FastAPI, Uvicorn, SQLite3)
* **Frontend**: HTML5, Tailwind CSS, Alpine.js, FullCalendar 6, Lucide Icons, Canvas-Confetti
* **Base de Dados**: SQLite (`ferias.db` criado automaticamente com dados de teste)
