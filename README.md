# Sistema de Impressão — Colégio Ranieri

Portal web que organiza as solicitações de impressão do colégio. Os professores
enviam o PDF pelo navegador, o pedido entra numa fila, e um agente instalado no
computador ligado à impressora manda imprimir dentro do horário de expediente.

O objetivo é tirar o Departamento de T.I. do meio do caminho (nada de
e-mail com prova em anexo) e, ao mesmo tempo, deixar registrado
**quem pediu o quê, quando, e o que foi impresso**.

## Documentação

| Documento | Para quê |
|---|---|
| [docs/ARQUITETURA.md](docs/ARQUITETURA.md) | Como as peças se encaixam, banco de dados e cargos |
| [docs/MANUTENCAO.md](docs/MANUTENCAO.md) | **Manutenção preventiva**: rotinas, backup e solução de problemas |
| [docs/API.md](docs/API.md) | Referência das rotas (para diagnóstico) |
| [docs/MIGRACAO-VM-WINDOWS.md](docs/MIGRACAO-VM-WINDOWS.md) | **Levar o servidor para uma VM Windows** (o caminho adotado) |
| [docs/MIGRACAO-UBUNTU.md](docs/MIGRACAO-UBUNTU.md) | O mesmo, numa VM Ubuntu (caminho alternativo) |

## As três peças

```
Navegador do professor          Servidor (VM)                PC da impressora
┌────────────────────┐     ┌──────────────────────┐     ┌────────────────────┐
│  Front-end React   │────▶│  app.py (Flask)      │◀────│ agente_impressao.py│
│  porta 5173        │ HTTP│  porta 8080          │ HTTP│  (consulta a cada  │
│                    │     │  SQLite + PDFs       │     │   15s)             │
└────────────────────┘     └──────────────────────┘     └─────────┬──────────┘
                                                                   │
                                                           SumatraPDF.exe
                                                                   │
                                                          Konica Minolta
```

O agente é o **único** componente que fala com a impressora. O servidor nunca
imprime — ele só guarda a fila e responde ao agente.

## Início rápido

Pré-requisitos: Python 3.11+ (por causa do `zoneinfo`), Node.js 18+ e as filas
da Konica instaladas no Windows do PC da impressora.

```powershell
# 1. Dependências do backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Configuração — copie e preencha os valores
copy .env.example .env
copy agente.env.example agente.env

# 3. Servidor (terminal 1)
.\.venv\Scripts\python.exe app.py          # http://localhost:8080

# 4. Front-end (terminal 2)
cd Front-end
npm install
npm run dev                                 # http://localhost:5173

# 5. Agente, no PC da impressora (terminal 3)
.\.venv\Scripts\python.exe agente_impressao.py
```

> As chaves `AGENTE_API_KEY` do `.env` e do `agente.env` precisam ser
> **idênticas**, senão o agente recebe "Não autorizado" e nada é impresso.
> Veja [docs/MANUTENCAO.md](docs/MANUTENCAO.md#variáveis-de-ambiente).

## Estrutura do repositório

```
app.py                    API Flask: login, fila, envio, relatórios, admin
banco_dados/__init__.py   Único lugar que toca o SQLite (usuários, pedidos, auditoria)
agente_impressao.py       Agente que roda no PC da impressora
automacao_impressora.py   Traduz as opções do pedido em um comando de impressão
horario_impressao.py      Faixa de horário de impressão (compartilhada servidor/agente)
opcoes_impressao.py       Regras de folhas/frente e verso (compartilhadas servidor/agente)
testar_impressao.py       Teste manual de impressão, sem passar pela fila
deploy/ubuntu/            systemd, nginx, backup e instalador da VM Linux
SumatraPDF.exe            Utilitário que envia o PDF para a fila do Windows (não vem no repositório: baixe a versão portátil em sumatrapdfreader.org)
requirements.txt          Dependências Python
Front-end/                Aplicação React + Vite
  src/app/App.tsx         Tela principal e roteamento por cargo
  src/app/components/     Formulários, fila, relatórios, painel de usuários
docs/                     Esta documentação
```

## Cargos

| Cargo | Enxerga | Pode editar |
|---|---|---|
| **T.I.** | Tudo | Usuários e relatórios (status de pedido é alterado só pelo agente) |
| **Diretor Administrativo** | Fila completa + relatório de custos | Não |
| **Diretora Pedagógica** | Fila completa + relatório por matéria (abre PDFs) | Não |
| **Coordenação de Segmento** | Fila e relatório por professor dos **seus segmentos** (Geral = tudo) | Não |
| **Coordenador** (professor) | Apenas os próprios envios | Não |

Detalhes em [docs/ARQUITETURA.md](docs/ARQUITETURA.md#cargos-e-permissões).
