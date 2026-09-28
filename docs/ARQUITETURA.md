# Arquitetura

Público-alvo: quem for dar manutenção no sistema. Para as rotinas do dia a dia,
veja [MANUTENCAO.md](MANUTENCAO.md).

## Visão geral

O sistema tem três processos independentes. Eles só conversam por HTTP — nenhum
deles compartilha arquivos ou memória com o outro.

| Processo | Onde roda | Porta | Responsabilidade |
|---|---|---|---|
| `app.py` (Flask) | Servidor / VM | 8080 | API, autenticação, banco de dados, fila |
| `Front-end` (Vite) | Servidor / VM | 5173 | Interface no navegador dos professores |
| `agente_impressao.py` | PC ligado à impressora | — | Busca pedidos e manda imprimir |

### Por que o agente existe

O servidor pode estar numa VM sem acesso à impressora física. O agente resolve
isso invertendo o sentido da conexão: em vez de o servidor "empurrar" a
impressão, o agente **puxa** os pedidos pendentes a cada 15 segundos. Assim o
PC da impressora não precisa aceitar conexões de fora — basta ter internet/rede
para alcançar o servidor.

## Fluxo de uma impressão

```
1. Professor faz login            POST /api/login          → recebe token assinado (12h)
2. Envia o PDF                    POST /api/enviar         → grava pedido (status "Pendente")
                                                             conta páginas, calcula SHA-256,
                                                             registra evento de auditoria
3. Agente pergunta o que há       GET  /api/agente/pendentes
4. Agente baixa o PDF             GET  /api/agente/arquivo/<id>
5. Agente avisa que começou       POST /api/agente/status/<id>  {"status":"Imprimindo"}
6. SumatraPDF.exe → fila Konica
7. Agente avisa o resultado       POST /api/agente/status/<id>  {"status":"Concluído"|"Erro"}
8. Front-end atualiza sozinho     GET  /api/fila           (a cada 8s na tela da fila)
```

**Horário de impressão: 08:00 às 18:00 por padrão** (fuso `America/Sao_Paulo`).
Fora dessa faixa o agente simplesmente não busca pedidos — eles ficam
"Pendente" e são processados na ordem de chegada quando o horário abre. Isso é
comportamento esperado, **não é falha**.

A faixa vive em `horario_impressao.py`, compartilhado pelos dois processos, e
se configura pelo ambiente (`HORARIO_INICIO_IMPRESSAO` / `HORARIO_FIM_IMPRESSAO`
/ `HORARIO_SO_DIAS_UTEIS`) — ver
[MANUTENCAO.md](MANUTENCAO.md#horário-de-impressão). O módulo é compartilhado
porque as constantes duplicadas saíram de sincronia na prática: o agente foi
alterado, o servidor não, e o professor passou a receber um horário que não
era o real.

## Autenticação e autorização

Toda a identidade vem de um **token assinado** (biblioteca `itsdangerous`),
gerado no login e válido por **12 horas**. O token carrega `name`, `role`,
`isSuperAdmin`, `uid`, `metodo`, `segmento` (único, quando a conta tem um só)
e `segmentos` (lista completa — a conta pode participar de mais de um).

Decisões importantes:

- **O cliente nunca informa quem é.** O nome e o cargo saem de dentro do token,
  nunca de um parâmetro da URL. Antes de existir o token, bastava trocar o nome
  na query string para ver a fila de outra pessoa.
- **A assinatura depende de `ACALANTO_SECRET_KEY`.** Se essa chave mudar, todos
  os tokens existentes ficam inválidos e todo mundo precisa entrar de novo.
- **O agente usa outra chave** `AGENTE_API_KEY`, cabeçalho `Authorization:
  Bearer …`), separada da dos usuários e exclusiva das rotas `/api/agente/*`.
- **Login Google:** a rota `POST /api/login/google` ainda existe no backend, mas
  o front-end não a utiliza — o botão foi removido porque o sistema roda numa VM
  sem o fluxo OAuth. O acesso é só por conta local.

### Cargos e permissões

Definidos em `banco_dados/__init__.py` (`PAPEIS_VALIDOS`, `PAPEIS_DIRETORIA`)
e espelhados no front em `types.ts` (`isDiretoria`, `podeVerRelatorios`).
Quem enxerga o quê é decidido em tempo de execução por `escopo_de_visao()`
em `app.py` — não existe um conjunto fixo de "visão global", porque a visão
da Coordenação depende dos segmentos da conta.

> Turmas e matérias seguem o mesmo arranjo: a lista de verdade é
> `TURMAS_VALIDAS` / `MATERIAS_VALIDAS` em `banco_dados/__init__.py`, espelhada
> em `types.ts` (`TURMAS_POR_SEGMENTO`, `MATERIAS`). Mexeu em uma, mexa na
> outra — quem recusa o envio é o servidor, então uma turma que só exista no
> front aparece na tela e depois dá `400`.

| Capacidade | Coordenador | Coordenação | Diretor Adm. | Diretora Ped. | T.I. |
|---|:---:|:---:|:---:|:---:|:---:|
| Ver a própria fila | ✓ | ✓ | ✓ | ✓ | ✓ |
| Ver a fila do(s) próprio(s) segmento(s) | — | ✓ | — | — | — |
| Ver a fila de todos (com remetente) | — | ✓ *(se Geral está entre os segmentos)* | ✓ | ✓ | ✓ |
| Enviar impressão | ✓ (matéria/turma) | ✓ (matéria/turma) | ✓ (assunto) | ✓ (assunto) | ✓ |
| Relatório por professor | — | ✓ *(travado no segmento)* | — | — | ✓ |
| Relatório de custos (P&B × colorida) | — | — | ✓ | — | ✓ |
| Relatório por matéria + abrir PDFs | — | — | — | ✓ | ✓ |
| Abrir PDF de terceiros | — | ✓ *(só do próprio segmento)* | — | ✓ | ✓ |
| Gerenciar usuários | — | — | — | — | ✓ |
| Cancelar pedido próprio (enquanto na fila) | ✓ | ✓ | ✓ | ✓ | ✓ |
| Alterar status de pedido | — | — | — | — | — |

> Status de pedido só muda pelo **agente local** (`POST /api/agente/status`,
> com a `AGENTE_API_KEY`) — não existe rota para um usuário, nem para o T.I.,
> alterar status pela interface. Os botões "Avançar"/"Reimprimir" da tela da
> fila são placeholders que hoje só exibem um aviso.

> ARMADILHA DE NOME: **Coordenador** (`ROLE_COORDENADOR`, professor comum —
> vê e envia só o que é seu) e **Coordenação** (`ROLE_COORDENACAO`,
> coordenadora de segmento — supervisiona) são cargos diferentes, apesar do
> nome parecido. É assim que o colégio chama os dois; não renomeie o valor
> gravado no banco, contas reais dependem dele.

Regras que valem a pena conhecer:

- **Auto-cadastro sai sempre como Coordenador.** Promover alguém a Coordenação,
  Diretoria ou T.I. é feito pelo painel **Usuários**, só pelo T.I. — o
  auto-cadastro nunca concede supervisão.
- **`super_admin`** é um privilégio à parte do cargo. Hoje só a conta `admin`
  tem. Ele permite alternar a *visualização* entre os cargos (menu do
  canto superior direito) — útil para testar telas sem criar contas.
- **Proteções no painel de usuários:** ninguém altera ou remove a própria conta,
  e um T.I. comum não mexe na conta `super_admin`.
- **A área da Diretoria** (Administrativa / Pedagógica) é derivada do cargo
  **no servidor**. O formulário mostra a área, mas o valor enviado pelo
  navegador é ignorado.

### Segmentos e escopo de visão

Quatro coordenações: **Educação Infantil**, **Fundamental I**, **Fundamental
II** e **Geral** (`SEGMENTO_INFANTIL`/`FUND1`/`FUND2`/`GERAL` em
`banco_dados/__init__.py`, espelhadas em `types.ts`). `GERAL` não é "mais um
segmento de turma": é ao mesmo tempo o escopo de quem enxerga a escola inteira
(`COORDENACAO` com esse segmento) e o bucket dos pedidos do Ensino Médio —
hoje a mesma pessoa acumula os dois papéis, então não existe `SEGMENTO_MEDIO`
separado. Se um dia houver uma coordenadora dedicada ao Médio, basta cadastrar
a conta dela com um segmento próprio.

Cada **pedido** é carimbado com o segmento **no momento do envio** — não é
derivado do professor na hora da consulta. Dois motivos: `professor_nome` é
texto livre sem FK (renomear a conta não pode quebrar o histórico), e quem dá
aula em mais de um segmento (inglês, educação física...) não tem um segmento
fixo que sirva pra todo pedido que manda. Pedidos antigos (de antes da coluna
existir) ou institucionais (Diretoria) ficam com `segmento: null` — visíveis
a T.I., Diretoria e Coordenação Geral, nunca às coordenadoras de um segmento
específico.

`escopo_de_visao(sessao)`, em `app.py`, é o **único lugar** que decide o que
alguém enxerga (fila, relatório, abrir documento) — todas as rotas chamam
essa função em vez de reimplementar a regra, porque escopo espalhado por
rota é como vaza permissão. Ela devolve sempre um de três casos, e o
`else` final é **sempre** o mais restritivo:

```
("TUDO", None)              → T.I., Diretoria, COORDENACAO com GERAL entre
                               os segmentos
("SEGMENTO", ["FUND1", …])  → COORDENACAO daqueles segmentos (a conta pode
                               cobrir mais de um; a lista nunca vem vazia)
("PROPRIO", None)           → COORDENADOR comum, e qualquer caso não
                               reconhecido (ex.: COORDENACAO sem segmento
                               válido — nunca vira "vê tudo" por acidente)
```

Os segmentos da sessão vêm de dentro do **token assinado** (ver acima), não
de uma nova consulta ao banco a cada requisição. Um filtro pedido pelo
cliente (`?segmento=...` em `/api/relatorio`) só pode **estreitar** esse
escopo, nunca alargá-lo: para quem já está travado em `SEGMENTO`, o valor da
query é ignorado.

## Banco de dados

SQLite em `banco_dados/acalanto_print.db`. O arquivo **não está no Git**
(`.gitignore`) — ele é o dado real e precisa de backup próprio.

Todo acesso ao banco passa por `banco_dados/__init__.py`. O `app.py` não escreve
SQL de usuários/credenciais.

### `pedidos`

| Coluna | Observação |
|---|---|
| `id` | Vira o protocolo mostrado ao professor (`IMP-0042`) |
| `professor_nome`, `usuario_uid`, `usuario_metodo` | Quem enviou. O `uid` (username) identifica a conta de forma única — o nome pode se repetir |
| `materia`, `turma` | No envio da Diretoria: `materia` = assunto, `turma` = área |
| `segmento` | Carimbado no envio (`INFANTIL`/`FUND1`/`FUND2`/`GERAL`). `NULL` = não definido (pedidos antigos ou institucionais da Diretoria) — nunca inferido a partir da turma |
| `folhas` | Folhas de **papel** do pedido (páginas ÷ 2 em frente e verso, × cópias). Gravada no envio, não calculada no relatório: o relatório vira `SUM()`, e se a regra mudar o pedido antigo preserva o número que era verdade |
| `reservado_em` | Quando o agente reservou o pedido. É o relógio que devolve à fila o que ficou preso em "Imprimindo" |
| `erro_motivo` | Causa do erro em português, vinda do agente — o que o professor lê na fila |
| `copias`, `cor`, `frente_verso`, `acabamento` | Opções de impressão |
| `arquivo_nome`, `arquivo_conteudo` | O PDF fica como **BLOB** no banco |
| `arquivo_hash` | SHA-256 do PDF — prova de integridade mesmo após a purga |
| `arquivo_purgado` | `1` quando a retenção descartou o conteúdo |
| `paginas` | Contado com `pypdf` no envio. Impressões = `paginas × copias` |
| `status` | `Pendente` → `Imprimindo` → `Concluído` \| `Erro`. O front-end exibe `Concluído` como "Enviado à impressora" — o valor do banco foi mantido porque relatórios, cota e purga dependem dele |
| `criado_em`, `atualizado_em`, `impresso_em` | Texto ISO 8601 no fuso de São Paulo. `impresso_em` guarda a hora da **entrega à impressora**, não da saída do papel — o nome ficou de antes de a distinção existir |

> **Por que o PDF vai para o banco e não para uma pasta:** o arquivo precisa
> sobreviver a reinícios e redeploys, e o backup do sistema passa a ser um único
> arquivo. O preço é que **o banco cresce** — ver
> [MANUTENCAO.md](MANUTENCAO.md#o-banco-está-crescendo-demais).

### `eventos` (trilha de auditoria)

Só recebe inserções — nunca é atualizada nem apagada. Registra a criação do
pedido, cada mudança de status (com o ator: nome do usuário ou `agente`) e a
remoção de arquivo por retenção. É o que sustenta a prestação de contas.

### `usuarios_locais`

`username` (chave), `senha_hash` (hash Werkzeug — a senha **nunca** é gravada em
texto), `nome_completo`, `role`, `super_admin`, `segmento`, `token_version`.

`token_version` vai dentro do token de sessão e é conferido a cada
requisição: trocar ou resetar a senha incrementa o número e **derruba as
sessões já abertas** daquela conta. Sem isso, uma senha comprometida
continuava valendo por até 12h, porque o token é assinado e sem estado.

`segmento` tem efeito diferente por cargo: para um `COORDENADOR` é só o valor
que pré-preenche o formulário de envio (sem efeito de permissão); para uma
`COORDENACAO` é o que define o escopo de visão (ver acima). `NULL` = "não
definido" — o painel de usuários destaca essas contas para o T.I. preencher.

A coluna aceita **mais de um segmento**, separados por vírgula
(`"FUND1,FUND2"`) — para o coordenador de área que dá aula em dois segmentos
e para a coordenação que cobre dois. Um valor antigo de código único continua
sendo lido normalmente (não houve migração de dados); quem interpreta é
`normalizar_segmentos()` em `banco_dados/__init__.py`. O segmento de um
**pedido** segue sendo um só.

### `usuarios_workspace`

Legado do login Google. Mantida por compatibilidade; sem uso no fluxo atual.

## Decisões e limitações conscientes

| Decisão | Motivo | Consequência para a manutenção |
|---|---|---|
| PDFs como BLOB no SQLite | Backup e portabilidade simples | O arquivo `.db` cresce; use a retenção |
| Token de 12h, sem refresh | Simplicidade; evita cookie entre IPs | Usuários relogam uma vez por dia |
| Retenção roda na **inicialização** do servidor | Não há agendador no projeto | Se o servidor nunca reinicia, a purga nunca acontece |
| Horário configurável, mas em dois `.env` separados | Servidor e agente rodam em máquinas diferentes | Os dois precisam do mesmo valor: o servidor promete o horário, o agente é quem cumpre |
| Grampo escolhido por fila, cor e duplex por comando | Cor e duplex são campos padrão do Windows; grampo é área privada do driver da Konica | Duas filas bastam. Uma variante nova de grampo exigiria uma fila nova |
| SQLite | Volume baixo (uma escola) | Não escala para escrita concorrente pesada |
| Status muda só pelo agente | O agente é quem sabe o resultado real | Os botões "Avançar/Reimprimir" da tela do T.I. ainda são placeholders |
| `Concluído` comprova **entrega**, não impressão | A Konica é compartilhada por um servidor de impressão; o agente entrega o trabalho e observa a fila, mas não enxerga dentro do equipamento | Papel acabando no meio do trabalho ou recusa por cota no painel passam despercebidos. O front-end exibe "Enviado à impressora" para não prometer mais do que isso |

## Onde mexer para cada tipo de mudança

| Quero mudar… | Arquivo |
|---|---|
| Horário de impressão | `.env` e `agente.env` (`HORARIO_*`); lógica em `horario_impressao.py` |
| Ligar o modo de desenvolvimento | `MODO_DESENVOLVIMENTO=true` **nos dois** `.env` — ver [MANUTENCAO.md](MANUTENCAO.md#para-testar-fora-do-horário) |
| Nomes das filas da Konica | `agente.env` (`IMPRESSORA_FILA_*`); padrões em `automacao_impressora.py` |
| Regras de cargo/permissão | `banco_dados/__init__.py` + `Front-end/src/app/components/types.ts` |
| Escopo de visão / segmentos | `escopo_de_visao()` em `app.py` + constantes `SEGMENTO_*` em `banco_dados/__init__.py` |
| Campos do formulário do professor | `Front-end/src/app/components/SubmissionForm.tsx` |
| Campos do formulário da Diretoria | `Front-end/src/app/components/SubmissionFormDiretoria.tsx` |
| Relatórios | `banco_dados/__init__.py` (consultas) + `ReportsPanel.tsx` (telas) |
| Limite de tamanho de upload | `app.py` (`MAX_UPLOAD_BYTES`) e `FileDropzone.tsx` |
