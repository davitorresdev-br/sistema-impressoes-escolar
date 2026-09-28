# Manutenção preventiva

Runbook do Departamento de T.I. para manter o Sistema de Impressão saudável.
Para entender *por que* as coisas funcionam assim, veja
[ARQUITETURA.md](ARQUITETURA.md).

## Acessos necessários

- Acesso administrativo à **VM/servidor** (onde rodam `app.py` e o front-end).
- Acesso ao **PC ligado à impressora** (onde roda `agente_impressao.py`).
- Conta com cargo **T.I.** no sistema (para o painel Usuários e os relatórios).
- Local de **backup** fora da VM (pasta de rede, HD externo ou nuvem).

## Subir e derrubar os serviços

```powershell
# Servidor (na raiz do projeto)
.\.venv\Scripts\python.exe app.py            # Ctrl+C para parar

# Front-end
cd Front-end
npm run dev                                   # desenvolvimento (porta 5173)
npm run build                                 # gera dist/ para produção

# Agente (no PC da impressora)
.\.venv\Scripts\python.exe agente_impressao.py
```

O agente imprime no console o que está fazendo. Deixe essa janela visível — é
o primeiro lugar a olhar quando "não está imprimindo".

## Variáveis de ambiente

Ficam em `.env` (servidor) e `agente.env` (PC da impressora). **Nenhum dos dois
está no Git** — guarde os valores em local seguro, porque perdê-los significa
reconfigurar o sistema.

### `.env` — servidor

| Variável | Padrão | Para que serve |
|---|---|---|
| `ACALANTO_SECRET_KEY` | *(inseguro)* | Assina os tokens de login. **Trocar derruba todas as sessões.** |
| `AGENTE_API_KEY` | vazio | Autentica o agente. Vazio = agente bloqueado. Deve ser **igual** à do `agente.env` |
| `ACALANTO_RETENCAO_DIAS` | `0` | Dias até descartar o PDF já impresso. `0` = nunca |
| `ACALANTO_LIMITE_MENSAL_FOLHAS` | `0` | Cota mensal por usuário, em **folhas de papel**. `0` = ilimitado (o nome antigo `ACALANTO_LIMITE_MENSAL_IMPRESSOES` ainda é aceito) |
| `ACALANTO_MAX_FOLHAS` | `500` | Teto de folhas por envio. `0` desliga |
| `ACALANTO_AUTOCADASTRO` | `aberto` | `fechado` faz as contas nascerem só pelo painel do T.I. |
| `ACALANTO_SENHA_MINIMA` | `8` | Tamanho mínimo de senha |
| `ACALANTO_LOGIN_MAX_TENTATIVAS` / `ACALANTO_LOGIN_JANELA_SEGUNDOS` | `5` / `300` | Limite de tentativas de login, por conta e por IP |
| `ACALANTO_MINUTOS_PEDIDO_PRESO` | `20` | Minutos em "Imprimindo" após os quais o pedido volta à fila |
| `ACALANTO_LOTE_AGENTE` | `20` | Quantos pedidos o agente recebe por ciclo |
| `ACALANTO_LOG` | `servidor.log` | Arquivo de log rotativo do servidor |
| `ACALANTO_HOST` / `ACALANTO_PORT` | `0.0.0.0` / `8080` | Onde o servidor escuta. Com nginx na frente, use `127.0.0.1` |
| `ACALANTO_ATRAS_DE_PROXY` | `false` | `true` **apenas** com proxy reverso — ver [MIGRACAO-UBUNTU.md](MIGRACAO-UBUNTU.md) |
| `ACALANTO_CORS_ORIGINS` | `*` | Origens liberadas. Pode restringir aos IPs do colégio |
| `ACALANTO_DEBUG` | `false` | **Nunca** `true` em produção (permite execução de código) |
| `GOOGLE_CLIENT_ID` | — | Legado do login Google (não usado) |
| `HORARIO_INICIO_IMPRESSAO` / `HORARIO_FIM_IMPRESSAO` | `08:00`/`18:00` | O servidor usa para **avisar** o professor; configure os mesmos valores no `agente.env` |
| `HORARIO_SO_DIAS_UTEIS` | `false` | Idem — só afeta as mensagens no servidor |
| `MODO_DESENVOLVIMENTO` | `false` | No servidor, **fecha o sistema** para todo mundo menos o super_admin — ver [Para testar fora do horário](#para-testar-fora-do-horário) |

### `agente.env` — PC da impressora

| Variável | Padrão | Para que serve |
|---|---|---|
| `CLOUD_URL` | `http://localhost:8080` | Endereço do servidor, sem barra no final. O padrão é o servidor da própria máquina — só defina quando o app.py estiver em outro lugar |
| `AGENTE_API_KEY` | vazio | Igual à do `.env` do servidor |
| `AGENTE_INTERVALO_SEGUNDOS` | `15` | De quanto em quanto tempo consulta a fila |
| `HORARIO_INICIO_IMPRESSAO` | `08:00` | Ver [Horário de impressão](#horário-de-impressão) |
| `HORARIO_FIM_IMPRESSAO` | `18:00` | Idem |
| `HORARIO_SO_DIAS_UTEIS` | `false` | `true` = não imprime sábado nem domingo |
| `MODO_DESENVOLVIMENTO` | `false` | Ignora a faixa de horário. **Nunca em produção** — ver [Para testar fora do horário](#para-testar-fora-do-horário) |
| `IMPRESSORA_FILA_NORMAL` | `\\SERVIDOR\Impressora (Normal)` | Fila para pedido sem grampo |
| `IMPRESSORA_FILA_GRAMPO` | `\\SERVIDOR\Impressora (Grampo)` | Fila para pedido com grampo |
| `SUMATRAPDF_EXE` | `SumatraPDF.exe` na raiz | Caminho do executável que imprime |
| `IMPRESSORA_TIMEOUT_SEGUNDOS` | `300` | Teto para entregar o trabalho ao spooler |
| `IMPRESSORA_VIGIA_SEGUNDOS` | `10` | Por quanto tempo observar a fila do servidor depois de enviar. `0` desliga |

> O nome da fila tem que ser **idêntico** ao que aparece em
> `Get-Printer | Select-Object Name` — ver [Filas de impressão](#filas-de-impressão).

Depois de alterar qualquer `.env`, **reinicie** o processo correspondente — as
variáveis são lidas só na inicialização.

---

## Horário de impressão

A faixa vale para os **dois** processos e vive em `horario_impressao.py`, mas
não precisa editar código: é configurável pelo ambiente.

```bash
HORARIO_INICIO_IMPRESSAO=07:00
HORARIO_FIM_IMPRESSAO=19:00
HORARIO_SO_DIAS_UTEIS=false
```

Padrão: **08:00–18:00, todos os dias**.

> **Configure nos dois arquivos.** O `.env` do servidor e o `agente.env` do PC
> da impressora são independentes. O servidor só usa a faixa para avisar o
> professor ("será impresso a partir das…"); quem realmente segura os pedidos
> é o agente. Valores diferentes fazem o sistema prometer um horário e cumprir
> outro — foi exatamente o que aconteceu quando as constantes eram fixas em
> cada arquivo.

Depois de alterar, **reinicie os dois**. Para conferir o que o agente entendeu,
olhe as primeiras linhas do console dele na inicialização:

```
[Agente] Iniciado. Consultando https://sua-app.discloud.app a cada 15s.
[Agente] Horário de impressão: 07:00–19:00.
```

Fora da faixa, os pedidos **não se perdem**: ficam "Pendente" e saem por ordem
de chegada quando o horário abrir.

### Detalhes

- Formato `HH:MM`, 24 horas. Valor inválido é ignorado com aviso no console e
  cai no padrão — o processo não morre por causa de um `.env` mal digitado.
- Os limites são inclusivos: `18:00` ainda imprime, `18:01` não.
- Faixa que atravessa a meia-noite funciona (`22:00`–`06:00`).
- `HORARIO_SO_DIAS_UTEIS` era o que a documentação antiga já prometia
  ("dias úteis") sem que o código verificasse. Agora existe de verdade, mas o
  padrão continua imprimindo todo dia para não mudar o comportamento de quem
  já usa o sistema — ligue se for o caso do colégio.

### Para testar fora do horário

Para validar a **impressora** (cor, frente e verso, grampo), não mexa no
horário: um teste de bancada chama a impressão direto, sem passar pelo agente
nem pela fila.

Para testar o **fluxo inteiro** fora do expediente, use o modo de
desenvolvimento — nos dois `.env`:

```bash
MODO_DESENVOLVIMENTO=true
```

Reinicie os dois processos. A faixa passa a ser ignorada e ambos avisam na
inicialização:

```
==================================================================
  ATENÇÃO: MODO_DESENVOLVIMENTO ligado em agente_impressao.py.
  A faixa de horário está sendo IGNORADA — imprime a qualquer hora.
  Remova MODO_DESENVOLVIMENTO do .env antes de usar em produção.
==================================================================
```

O painel do professor também troca "08:00 às 18:00" por "Sem limite de
horário", para a tela não anunciar uma regra que não está valendo.

**Enquanto está ligado, só o administrador-mestre entra no sistema.** Todas as
outras contas — inclusive as de cargo T.I. — recebem "O sistema está em
manutenção no momento" ao tentar entrar, e as sessões que já estavam abertas
param de funcionar na hora. O auto-cadastro também fica fechado.

Isso é parte do que torna o modo seguro: testar fora do expediente significa
imprimir de verdade em horário esquisito, e um professor entrando nesse
intervalo teria os trabalhos dele misturados aos de teste na mesma Konica.

O critério é a conta **super_admin** no banco, não o cargo T.I. — o cargo pode
estar com várias pessoas do Departamento, enquanto o administrador-mestre é a
conta única de quem está conduzindo o teste.

As rotas do agente (`/api/agente/*`) continuam funcionando normalmente, porque
usam a `AGENTE_API_KEY` e não uma conta de usuário. Sem isso não haveria o que
testar.

> **Ele só desliga o horário e o acesso.** O agente continua imprimindo de
> verdade, na Konica de verdade, gastando papel de verdade — não é um modo que
> simula impressão. E **nunca** deve ficar ligado em produção: além de imprimir
> de madrugada e no fim de semana, ninguém consegue usar o sistema.

Preferir isto a alargar a faixa manualmente evita o problema clássico de
alterar os dois `.env` e esquecer de desfazer um deles.

---

## Filas de impressão

Quem imprime é o **SumatraPDF.exe**, que recebe as opções por trabalho:

```
SumatraPDF.exe -print-to "\\SERVIDOR\Impressora (Grampo)"
               -print-settings "30x,color,duplexlong"
               -silent -exit-when-done arquivo.pdf
```

> Só entram tokens que o binário 3.6.1 conhece de fato — `collate` e
> `ignore-pdf-print-settings` existem na documentação online (de versão mais
> nova), mas este executável os ignoraria **em silêncio**, então o código não
> os envia (ver `montar_print_settings` em `automacao_impressora.py`).

### Papel A3

Papel A3 **não passa pelo sistema** (decisão da gestão): A3 é impressão
especial, tratada diretamente com o T.I. Tudo sai no papel padrão da fila
(A4). Se um dia voltar a ser necessário, o token do SumatraPDF é
`paper=A3` — conferido dentro do binário 3.6.1, junto com `bin=`; o nome
precisa existir no driver da fila e a bandeja precisa ter A3 carregado.

A orientação (retrato/paisagem) **não** é configurada por token: ela vem de
dentro do próprio PDF, página a página — o SumatraPDF gira cada página para
caber no papel.

Cor e frente e verso são campos padrão do Windows (`dmColor` e `dmDuplex`),
então viajam no comando e **sobrescrevem o padrão do driver da fila**. Grampo
não tem campo padrão — vive na área privada do driver da Konica, que nenhuma
ferramenta genérica escreve. Por isso, e só por isso, existem duas filas:

| Variável no `agente.env` | Fila | Quando é usada |
|---|---|---|
| `IMPRESSORA_FILA_NORMAL` | `\\SERVIDOR\Impressora (Normal)` | Pedido sem grampo |
| `IMPRESSORA_FILA_GRAMPO` | `\\SERVIDOR\Impressora (Grampo)` | Pedido com grampo |

Como as opções vão explícitas em todo trabalho, **o padrão do driver dessas
filas não importa mais**. A fila de grampo está em `TwoSidedLongEdge`, mas um
pedido "apenas frente" manda `simplex` e sai só frente.

### Se precisar trocar de fila

O nome tem que ser **idêntico** ao do Windows. Confira no PC do agente:

```powershell
Get-Printer | Select-Object Name
```

Em impressora compartilhada o nome inclui o servidor
(`\\SERVIDOR\Impressora (Normal)`), não só o nome curto. Ajuste o `agente.env`
e **reinicie o agente**.

O agente confere a fila antes de disparar e recusa o pedido com a lista das
filas visíveis se o nome não bater — em vez de "imprimir" para o nada.

> As filas são lidas do **usuário que iniciou o agente**. Se o agente rodar
> como serviço ou por outra conta, ele pode não enxergar as conexões de rede
> do seu usuário. É a causa mais comum de "a fila existe, mas o agente diz que
> não".

### Limitações conhecidas

- **Grampo** só existe nas duas variantes acima. Grampo de 2 furos, canto vs.
  lateral etc. exigiriam mais filas.
- **Cor** pode ser barrada no próprio equipamento se a Konica estiver com
  restrição por departamento (Account Track). Nesse caso o `color` do comando
  é ignorado pela impressora, e não há o que fazer pelo software.

---

## Rotinas

### Diária (~2 minutos, de manhã)

1. A janela do **agente** está aberta e sem erro repetido no console?
2. Abra o sistema como T.I. → aba **Fila de Impressão**. Há pedido "Pendente"
   de ontem que deveria ter saído? Há pedidos em **"Erro"**?
3. Se algo estiver em "Erro", veja [Problemas comuns](#problemas-comuns).

> Pedidos "Pendente" **fora do [horário configurado](#horário-de-impressão) são
> normais** — o agente só
> imprime no expediente.

### Semanal (~10 minutos)

1. **Faça o backup** e confirme que o arquivo foi criado (ver [Backup](#backup-e-restauração)).
2. Verifique o **tamanho do banco**:
   ```powershell
   (Get-Item banco_dados\acalanto_print.db).Length / 1MB
   ```
   Crescendo rápido? Ver [O banco está crescendo demais](#o-banco-está-crescendo-demais).
3. Rode o [diagnóstico rápido](#diagnóstico-rápido) e olhe os erros da semana.
4. **Teste de ponta a ponta:** envie um PDF de 1 página por uma conta de teste e
   confirme que sai na impressora e vira "Concluído".

### Mensal (~30 minutos)

1. **Contas:** painel **Usuários** → remova quem saiu do colégio e confira se
   ninguém tem cargo além do necessário (principalmente T.I. e Diretoria).
2. **Relatórios:** gere o CSV do mês (Relatórios → período → Baixar CSV) e
   arquive junto da prestação de contas.
3. **Reinicie o servidor** — além de liberar memória, é o que dispara a purga de
   retenção (ela roda só na inicialização).
4. **Atualize as dependências** se houver correção de segurança:
   ```powershell
   .\.venv\Scripts\python.exe -m pip list --outdated
   cd Front-end; npm audit
   ```

### Semestral (~1 hora)

1. **Teste a restauração do backup** numa cópia — backup nunca restaurado não é
   backup. Passo a passo em [Restauração](#restauração).
2. **Rotacione as chaves** `ACALANTO_SECRET_KEY` e `AGENTE_API_KEY`
   (ver [Rotação de chaves](#rotação-de-chaves)).
3. Reveja os cargos de todo mundo e as senhas de contas administrativas.
4. Confirme que as filas da Konica no Windows continuam com os nomes **e os
   padrões de driver** esperados — ver [Filas de impressão](#filas-de-impressão).
   Uma atualização de driver pode reverter o duplex ou a cor sem avisar.

---

## Backup e restauração

**O que precisa de backup** (nada disso está no Git):

| Item | Caminho | Por quê |
|---|---|---|
| Banco de dados | `banco_dados/acalanto_print.db` | Usuários, pedidos, PDFs e auditoria |
| Config do servidor | `.env` | Chaves — sem elas o sistema não sobe igual |
| Config do agente | `agente.env` | Endereço e chave do agente |

### Backup do banco (pode ser feito com o sistema no ar)

Use a API de backup do SQLite — copiar o arquivo "na mão" com o sistema rodando
pode gerar cópia corrompida.

```powershell
$data = Get-Date -Format 'yyyy-MM-dd'
.\.venv\Scripts\python.exe -c "import sqlite3; s=sqlite3.connect(r'banco_dados\acalanto_print.db'); d=sqlite3.connect(r'D:\Backups\acalanto_$data.db'); s.backup(d); d.close(); s.close(); print('backup concluido')"
```

Troque `D:\Backups` pelo destino real (de preferência **fora da VM**).

Confira se a cópia está íntegra:

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print('integridade:', c.execute('PRAGMA integrity_check').fetchone()[0]); print('pedidos:', c.execute('SELECT COUNT(*) FROM pedidos').fetchone()[0]); print('usuarios:', c.execute('SELECT COUNT(*) FROM usuarios_locais').fetchone()[0])" D:\Backups\acalanto_2026-06-25.db
```

**Retenção sugerida:** um backup por semana guardado por 3 meses, mais um
backup mensal guardado por 1 ano.

### Restauração

> **Na VM Windows, use o script** — ele faz a sequência abaixo inteira e
> confere o resultado:
> `powershell -ExecutionPolicy Bypass -File deploy\windows\restaurar_banco.ps1`

À mão:

1. **Pare** o `app.py` (Ctrl+C) e o agente.
2. Tire do lugar os **três** arquivos do banco, renomeando em vez de apagar:
   ```powershell
   foreach ($s in @("", "-wal", "-shm")) {
       $a = "banco_dados\acalanto_print.db$s"
       if (Test-Path $a) { Rename-Item $a "acalanto_print.db$s.quebrado" }
   }
   ```
   **O `-wal` e o `-shm` têm que sair junto.** Desde que o banco passou a
   usar WAL, ele são três arquivos, e o backup é um banco *sozinho*, sem
   WAL. Se você trocar só o `.db`, o `-wal` do banco anterior fica na pasta
   e o SQLite tenta aplicá-lo sobre um arquivo que não é o dele — o
   resultado vai de "voltaram dados velhos" a banco corrompido, justamente
   quando você já está restaurando porque algo deu errado.
3. Ponha o backup no lugar:
   ```powershell
   Copy-Item D:\Backups\acalanto_2026-06-25.db banco_dados\acalanto_print.db
   ```
4. Confira **antes** de subir:
   ```powershell
   .\.venv\Scripts\python.exe deploy\conferir_banco.py
   ```
5. Suba o `app.py`. Ele aplica sozinho as migrações que faltarem.
6. Confira o login e a fila antes de liberar para os professores.
7. Avise que os pedidos feitos entre o backup e agora se perderam.

---

## Tarefas de manutenção

### Rotação de chaves

Gere um valor novo:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

- **`ACALANTO_SECRET_KEY`** (só no `.env` do servidor): troque, reinicie o
  `app.py`. Todos precisarão **entrar de novo** — avise antes.
- **`AGENTE_API_KEY`** (nos **dois** arquivos): atualize `.env` e `agente.env`
  com o **mesmo** valor e reinicie servidor e agente. Se ficarem diferentes, o
  agente recebe 401 e nada é impresso.

### Ligar a retenção de PDFs

No `.env`, defina por quantos dias o conteúdo do PDF já impresso é mantido:

```
ACALANTO_RETENCAO_DIAS=90
```

Reinicie o servidor. Na inicialização ele descarta o conteúdo dos PDFs
concluídos mais antigos que isso e registra o evento na auditoria. **O pedido, o
histórico e o hash SHA-256 continuam** — só o arquivo em si sai. Quem tentar
abrir um documento purgado recebe o aviso "expirado pela política de retenção".

> Como a purga roda apenas na inicialização, **reinicie o servidor
> periodicamente** (a rotina mensal já cobre isso).

### Ligar a cota mensal

```
ACALANTO_LIMITE_MENSAL_IMPRESSOES=2000
```

A conta é `páginas × cópias` por usuário, por mês. O envio que estouraria o
limite é recusado com uma mensagem orientando procurar o T.I.

### Gestão de contas

Tudo pelo painel **Usuários** (visível para o cargo T.I.):

- **Novo professor:** ele mesmo se cadastra na tela de login (sai como
  Coordenador). Ou cadastre pelo painel já com o cargo certo.
- **Promover/rebaixar:** seletor de cargo na linha do usuário.
- **Esqueceu a senha:** botão **Senha** → defina uma provisória e peça troca.
  A pessoa troca sozinha depois, no menu do próprio nome (canto superior
  direito) → **Trocar senha**, informando a provisória como senha atual.
  Não é preciso T.I. para trocar a senha do dia a dia — só para reset.
- **Saiu do colégio:** botão **Remover**. Os pedidos e a auditoria dele
  permanecem (prestação de contas), apenas o acesso é cortado.

Proteções: você não altera nem remove a própria conta por ali, e um T.I. comum
não mexe na conta `admin` (super_admin).

---

## Diagnóstico rápido

Salve como `scripts/diagnostico.py` e rode com
`.\.venv\Scripts\python.exe scripts\diagnostico.py`:

```python
"""Panorama rápido da saúde do sistema de impressão."""
import os, sqlite3
from datetime import datetime, timedelta

DB = os.path.join("banco_dados", "acalanto_print.db")
conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row; cur = conn.cursor()

print(f"Banco: {os.path.getsize(DB) / 1024 / 1024:.1f} MB\n")

cur.execute("SELECT status, COUNT(*) n FROM pedidos GROUP BY status")
print("Pedidos por status:")
for r in cur.fetchall():
    print(f"  {r['status']:12} {r['n']}")

ontem = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
cur.execute("SELECT COUNT(*) FROM pedidos WHERE status='Erro' AND criado_em > ?", (ontem,))
print(f"\nErros nas ultimas 24h: {cur.fetchone()[0]}")

cur.execute("""SELECT id, professor_nome, criado_em FROM pedidos
               WHERE status='Pendente' ORDER BY id ASC LIMIT 5""")
pend = cur.fetchall()
if pend:
    print("\nPendentes mais antigos:")
    for r in pend:
        print(f"  IMP-{r['id']:04d}  {r['professor_nome']}  {r['criado_em']}")

cur.execute("SELECT role, COUNT(*) n FROM usuarios_locais GROUP BY role")
print("\nContas por cargo:")
for r in cur.fetchall():
    print(f"  {r['role']:14} {r['n']}")

conn.close()
```

Sinais de alerta: pendentes com data antiga durante o expediente, erros
acumulando, banco crescendo muito rápido, ou contas com cargo T.I./Diretoria
que você não reconhece.

---

## Problemas comuns

### Nada é impresso — tudo fica "Pendente"

| Verifique | Como | Correção |
|---|---|---|
| Está no horário? | Primeira linha do console do agente mostra a faixa | Comportamento normal fora dela — ver [Horário de impressão](#horário-de-impressão) |
| O agente está rodando? | Janela do console no PC da impressora | Reinicie o agente |
| O agente autentica? | Console mostra "Não autorizado"/401 | `AGENTE_API_KEY` diferente entre `.env` e `agente.env` — iguale e reinicie os dois |
| O agente alcança o servidor? | `curl http://SERVIDOR:8080/api/fila` do PC da impressora | Rede/firewall: libere a porta 8080 |

### Pedidos viram "Erro" logo após "Imprimindo"

O console do agente mostra o motivo exato. Os mais comuns:

| Mensagem | O que fazer |
|---|---|
| `a fila '…' não existe no Windows` | O console lista as filas visíveis — ver [Filas de impressão](#filas-de-impressão) |
| `SumatraPDF.exe não encontrado` | O executável saiu da raiz do projeto, ou o `SUMATRAPDF_EXE` aponta para o lugar errado |
| `arquivo PDF não encontrado` | Pasta `temp_impressao` sem permissão de escrita |
| `SumatraPDF não respondeu em 300s` | Spooler travado. Reinicie o serviço **Spooler de Impressão** no PC do agente |
| `SumatraPDF falhou com código …` | PDF corrompido ou protegido por senha — peça outro arquivo ao professor |

### O que cada status realmente significa

| No banco | O que o professor lê | O que o sistema comprovou |
|---|---|---|
| `Pendente` | Pendente | Gravado, aguardando o agente |
| `Imprimindo` | Imprimindo | PDF baixado, prestes a ser enviado |
| `Concluído` | **Enviado à impressora** | Entregue ao servidor de impressão **e** não travou na fila |
| `Erro` | Erro | Falhou em alguma etapa — o console diz qual |

Os valores do banco não mudaram: são usados nos relatórios, na cota mensal e na
purga de PDFs. Só o texto exibido mudou.

**Por que não "Concluído".** O agente entrega o trabalho ao `SERVIDOR` e
observa a fila por alguns segundos. Isso cobre impressora offline, sem papel,
atolada ou pausada. **Não cobre** o que acontece dentro do equipamento depois:
papel acabando no meio do trabalho, ou o painel recusando por cota de
departamento. Chamar isso de "Concluído" era prometer o que ninguém verificou.

Se o professor diz que não saiu e o pedido está "Enviado à impressora", o
problema está entre o servidor de impressão e a bandeja — comece pelo painel do
equipamento, não pelo sistema.

### Pedidos saem com opção diferente da pedida

O comando exato vai para o console em toda impressão
(`💻 [Terminal Windows] Executando: …`). Confira o `-print-settings`: ele deve
trazer `color`/`monochrome` e `simplex`/`duplexlong` batendo com o pedido.

- **O comando está certo mas o papel sai errado** → o driver da Konica não
  está honrando a opção. Para cor, suspeite de restrição por departamento
  (Account Track) no equipamento.
- **O comando está errado** → o pedido chegou com valor inesperado nos campos
  `cor` / `frente_verso` / `acabamento`. A linha `💻 [Opções]` mostra o que
  veio do banco.

### Professor cai para a tela de login sozinho

O token vale **12 horas**. Depois disso é preciso entrar de novo — é o
comportamento esperado. Se acontecer com todo mundo ao mesmo tempo e fora do
prazo, alguém trocou a `ACALANTO_SECRET_KEY`.

### "Apenas arquivos PDF válidos são aceitos"

O arquivo não é PDF de verdade (extensão trocada) ou está corrompido. Peça para
reexportar como PDF. O limite de tamanho é **50 MB**.

### "Cota mensal … excedida"

`ACALANTO_LIMITE_MENSAL_IMPRESSOES` está ativo e o usuário chegou no teto.
Aumente o limite no `.env` (e reinicie) ou oriente o professor.

### "Arquivo expirado pela política de retenção" (410)

O PDF foi descartado pela retenção. É esperado — o registro, o histórico e o
hash continuam. Não há como recuperar o arquivo, exceto de um backup anterior à
purga.

### Tela branca no navegador

Abra o **Console (F12)** e leia a primeira linha vermelha. Costuma ser erro de
JavaScript após uma atualização — force `Ctrl+Shift+R` para recarregar. Se
persistir, rode `npm run build` e verifique se compila.

### Banco travado ("database is locked")

Duas escritas simultâneas no SQLite. Raro no volume do colégio. Se virar
rotina, verifique se não há **duas instâncias** do `app.py` rodando ao mesmo
tempo.

### O banco está crescendo demais

Os PDFs ficam dentro do banco. Sem retenção ligada, ele cresce para sempre.

1. Ligue `ACALANTO_RETENCAO_DIAS` (ver acima) e reinicie o servidor.
2. Depois da purga, recupere o espaço em disco (com o sistema **parado**):
   ```powershell
   .\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect(r'banco_dados\acalanto_print.db'); c.execute('VACUUM'); c.close(); print('vacuum ok')"
   ```
   > Faça backup antes e nunca rode o `VACUUM` com o `app.py` no ar.

---

## Atualizar o sistema

1. **Backup** do banco e dos `.env` (passo obrigatório).
2. Pare o `app.py` e o agente.
3. Traga as alterações (`git pull`) e atualize dependências:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   cd Front-end; npm install; npm run build
   ```
4. Suba o `app.py` — as migrações de banco são aplicadas automaticamente na
   inicialização (colunas novas são adicionadas sem perder dados).
5. Teste: login, envio de 1 PDF, fila atualizando, e uma impressão real.
6. Suba o agente e confirme no console que ele autenticou.

**Rollback:** volte o código (`git checkout <versão-anterior>`), restaure o
banco do backup e reinicie os dois processos.

---

## Quando escalar

Se o problema persistir após o runbook, reúna estas informações antes de pedir
ajuda:

- O que aconteceu, com qual usuário e a que horas.
- O **protocolo** do pedido (`IMP-0042`) e o status dele na fila.
- As últimas linhas do console do **agente** e do **servidor**.
- Erros do **Console (F12)** do navegador, se for problema de tela.
- Saída do [diagnóstico rápido](#diagnóstico-rápido).

A trilha de auditoria de um pedido específico responde "o que aconteceu com
ele" — consulte `GET /api/pedido/<id>/eventos` com uma conta T.I.
(ver [API.md](API.md)).
