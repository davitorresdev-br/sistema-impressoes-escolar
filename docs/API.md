# Referência da API

Todas as rotas ficam sob `/api` no servidor Flask (porta **8080**) e respondem
JSON, exceto onde indicado (PDF/CSV).

## Autenticação

Existem **duas** credenciais independentes:

| Tipo | Cabeçalho | Usado em | Origem |
|---|---|---|---|
| Token de usuário | `Authorization: Bearer <token>` | Rotas de usuário/admin | Devolvido pelo login; validade **12h** |
| Chave do agente | `Authorization: Bearer <AGENTE_API_KEY>` | Apenas `/api/agente/*` | `.env` / `agente.env` |

Códigos de resposta usados no projeto:

| Código | Significa |
|---|---|
| `400` | Dados inválidos (campo faltando, PDF inválido/protegido, teto de folhas, cargo inexistente) |
| `401` | Sem token, token expirado/adulterado/**revogado por troca de senha**, ou cargo sem permissão |
| `403` | Cota mensal excedida, modo de manutenção, auto-cadastro fechado, ou **cargo sem acesso** (sessão válida — o front não desloga) |
| `404` | Pedido/arquivo não encontrado (usuário inexistente nas rotas admin devolve `400`) |
| `409` | Nome de usuário já existe; envio duplicado; pedido já reservado ou fora da fila |
| `410` | Arquivo descartado pela política de retenção |
| `413` | Upload acima de 50 MB |
| `429` | Muitas tentativas de login (limite por conta e por IP) |

---

## Autenticação e contas

### `POST /api/login`
```json
{ "username": "professor.silva", "password": "…" }
```
Resposta: `{ "status": "sucesso", "name", "role", "isSuperAdmin", "segmento", "segmentos", "token" }`

`segmentos` é a lista de segmentos **cadastrados da conta** (a conta pode
participar de mais de um — ex.: `["FUND1", "FUND2"]`; vazia se não definido).
`segmento` (único) é mantido por compatibilidade: vem preenchido só quando a
conta tem exatamente um segmento, e `null` nos demais casos. Não confundir com
o **escopo de visão**, que `/api/fila` devolve à parte. A lista também vai
embutida dentro do `token`: é o que `escopo_de_visao()` usa para decidir o que
uma `COORDENACAO` enxerga, sem precisar reconsultar o banco a cada requisição.

### `POST /api/registrar`
Auto-cadastro. **Sempre cria como `COORDENADOR`**, sem privilégio — virar
`COORDENACAO` (supervisiona um segmento) é decisão do Departamento, feita no
painel de usuários; o auto-cadastro nunca concede supervisão. Já devolve o
token (o usuário entra direto).
```json
{ "name": "Marcos Souza", "username": "marcos.s", "password": "…", "segmentos": ["FUND1", "FUND2"] }
```
`segmentos` (lista) ou `segmento` (código único) é opcional e só pré-preenche
o formulário de envio. Senha mínima de 4 caracteres. `409` se o usuário já
existir.

> **`MODO_DESENVOLVIMENTO=true`** fecha o sistema para todo mundo menos o
> administrador-mestre (`super_admin`). `/api/login` e `/api/registrar`
> devolvem `403`, e `usuario_autenticado()` passa a recusar tokens de outras
> contas — inclusive os emitidos antes de o modo ser ligado. As rotas
> `/api/agente/*` não são afetadas: usam a `AGENTE_API_KEY`.

### `POST /api/senha`
Troca a senha da **própria** conta. Exige token.
```json
{ "senha_atual": "…", "nova_senha": "…" }
```
A conta alterada é sempre a do token — não há parâmetro de usuário, para não
existir caminho de trocar senha alheia. A senha atual é obrigatória: sem ela,
um token roubado bastaria para tomar a conta.

| Código | Quando |
|---|---|
| `400` | Campo vazio, nova senha com menos de 4 caracteres, ou nova igual à atual |
| `403` | Senha atual incorreta |
| `401` | Sem token ou token expirado |

> Trocar a senha **não derruba** sessões já abertas: o token é assinado e sem
> estado, então continua válido até expirar (12h). Para tirar alguém do ar na
> hora, o T.I. remove ou recria a conta.

### `POST /api/login/google`
Legado — o front-end não usa mais (sistema roda em VM sem OAuth).

---

## Fila e envio

### `GET /api/horario`
**Sem autenticação** (de propósito: é a mesma informação já visível na tela de
envio, e o painel lateral precisa dela antes de qualquer ação do usuário).
Devolve a faixa de horário em que a impressora aceita trabalhos:
```json
{ "inicio": "07:00", "fim": "17:00", "so_dias_uteis": true,
  "descricao": "07:00–17:00, em dias úteis",
  "aberto_agora": true, "modo_desenvolvimento": false,
  "agente_online": true, "agente_visto_em": "2026-08-24T10:31:02-03:00",
  "agente_segundos": 12 }
```

`agente_online` é o **sinal de vida do agente de impressão**: `true` se ele
deu sinal nos últimos 90s (`ACALANTO_SEGUNDOS_AGENTE_OFFLINE`), `false` se
parou de dar, e `null` se nunca houve sinal — nesse último caso o front não
acusa nada, porque afirmar "fora do ar" sem saber seria alarme falso. É o
que faz a tela avisar "a impressora está fora do ar desde 14:32" em vez de
deixar os pedidos acumulando com todo mundo achando que está tudo bem.

### `GET /api/fila`
Requer token. Parâmetro opcional `view_mode` (só tem efeito para `super_admin`,
que pode visualizar como qualquer cargo).

O **escopo é decidido no servidor**, por `escopo_de_visao()`, a partir do
token — nunca de um parâmetro que o cliente possa mandar:

| Escopo | Quem | Vê |
|---|---|---|
| `TUDO` | T.I., Diretoria, `COORDENACAO` com `GERAL` entre os segmentos | Todos os pedidos |
| `SEGMENTO` | `COORDENACAO` de um ou mais segmentos (`INFANTIL`/`FUND1`/`FUND2`) | Só pedidos daqueles segmentos |
| `PROPRIO` | `COORDENADOR`, e qualquer caso não reconhecido (ex.: `COORDENACAO` sem segmento cadastrado) | Só os próprios pedidos |

```json
{
  "estatisticas": { "pendentes": 3, "imprimindo": 1, "concluidos": 42 },
  "pedidos": [{
    "id": 43, "remetente": "Marina Costa",
    "materia": "Matemática", "turma": "3º EM",
    "materia_turma": "Matemática — 3º EM",
    "arquivo": "prova.pdf", "copias": 32, "paginas": 2,
    "posicao": "3º", "posicao_global": 3, "total_na_fila": 27,
    "status": "Pendente", "folhas": 64, "erro_motivo": null,
    "cancelavel": true,
    "criado_em": "2026-06-25T09:12:00-03:00", "impresso_em": null,
    "segmento": "FUND2", "segmento_rotulo": "Fundamental II"
  }],
  "escopo": { "tipo": "SEGMENTO", "segmento": "FUND2", "segmentos": ["FUND2"], "segmento_rotulo": "Fundamental II" }
}
```

> No `escopo`, `segmentos` traz **todos** os segmentos cobertos (uma
> coordenação pode cobrir mais de um) e `segmento_rotulo` já vem juntado
> ("Fundamental I e Fundamental II"). `segmento` (único) fica preenchido só
> quando o recorte cobre um segmento; com vários, vem `null`.

> `materia_turma` é o campo antigo, mantido para não quebrar quem já lia a fila.
> Use `materia` e `turma`: separar o campo unido pelo `" — "` errava quando o
> próprio texto da matéria trazia o separador.

> **`posicao_global` é a posição na fila da ESCOLA**, não entre os pedidos
> de quem pediu — a consulta já vem filtrada por escopo, e contar dentro
> dela diria "1º" para o primeiro pedido do professor mesmo havendo 30 na
> frente. Com `total_na_fila`, a tela escreve "3º de 27", que é honesto.
> `estatisticas.pendentes_global` traz o mesmo total; as outras contagens
> de `estatisticas` descrevem o que a pessoa vê (o escopo dela).

> `folhas` é papel (páginas ÷ 2 em frente e verso, × cópias);
> `erro_motivo` traz a causa em português quando o status é `Erro`; e
> `cancelavel` diz se ESTA pessoa pode cancelar ESTE pedido (é dona dele e
> ele ainda está na fila) — o front não recalcula a regra.

> `escopo` é o que o front usa para deixar explícito o que está em vigor
> ("Fila — Fundamental II" em vez de só "Fila de Impressão"). `segmento` em
> cada pedido é `null` para envios de antes desta coluna existir, ou da
> Diretoria (institucional, sem segmento).

### `POST /api/enviar`
Requer token. `multipart/form-data`. **O remetente vem do token** — não é
enviado pelo cliente.

| Campo | Quem envia | Observação |
|---|---|---|
| `arquivo` | todos | PDF válido, até 50 MB |
| `copias`, `cor`, `frente_verso`, `acabamento` | todos | Opções de impressão |
| `materia`, `turma` | Coordenador / Coordenação / T.I. | Listas fechadas + opção "Outro" — ver abaixo |
| `segmento` | Coordenador / Coordenação / T.I. | Opcional — ver abaixo |
| `assunto` | Diretoria | A área vem do cargo, **definida no servidor** |

`materia` aceita uma das 11 de `MATERIAS_VALIDAS` ou o texto livre da opção
"Outro" da tela (capa de avaliação, simulado). `turma` aceita um dos 16
valores de `TURMAS_VALIDAS` (`Maternal 1`–`3º EM`) ou, também, o texto livre
do "Outro" da tela — para impressão que não pertence a turma nenhuma (uso
próprio do professor, reunião de pais, formação). Os dois textos livres
passam por `normalizar_materia()`/`normalizar_turma()`: viram uma linha só,
sem caracteres de controle, cortados em 60. Se não sobrar nada, `400`.

> Papel A3 **não passa pelo sistema** (decisão da gestão): A3 é impressão
> especial, tratada diretamente com o T.I. Tudo sai no padrão da fila (A4).

`segmento` é **carimbado no pedido no momento do envio** (não derivado do
professor depois) — quem dá aula em mais de um segmento escolhe a cada envio.
O pedido carrega sempre **um** segmento (cada envio é de uma turma). Precisa
ser um dos valores de `SEGMENTOS_VALIDOS` (`INFANTIL`, `FUND1`, `FUND2`,
`GERAL`); se vier vazio ou inválido, cai no segmento cadastrado da conta —
mas **só quando a conta tem exatamente um** (com vários cadastrados não
existe "o" segmento para presumir); senão o pedido fica sem segmento
(`null`). Pedidos da Diretoria ficam sempre com `segmento: null`
(institucional, fora da classificação por segmento).

**Teto por envio:** o pedido é recusado (`400`) se passar de
`ACALANTO_MAX_FOLHAS` **folhas de papel** (padrão 500). A conta é em folhas,
não em páginas: 8 páginas em frente e verso × 60 cópias são 240 folhas, não
480 — recusar por "480" seria rejeição indevida. Quando o `pypdf` não
consegue contar as páginas, o pedido **não** é recusado (a biblioteca é mais
exigente que a impressora); o teto passa a valer pelo número de cópias, que
é o piso garantido, e o caso vai para o log.

**PDF protegido por senha** é recusado com explicação: o SumatraPDF não o
imprime e, com `-silent`, não reclama — o pedido terminaria "Concluído" sem
papel nenhum sair.

**Envio duplicado:** o mesmo arquivo (hash SHA-256), da mesma conta, nos
últimos 10 minutos devolve `409` com `{"erro": "duplicado", "mensagem": …}`.
Reenviar com `confirmar_duplicado=1` passa. Cobre o caso da página que
demorou e do segundo clique, que saía em dobro.

Resposta: `{ "status": "sucesso", "mensagem", "protocolo": "IMP-0043", "pedido_id": 43, "paginas": 2, "folhas": 64 }`

### `POST /api/pedido/<id>/cancelar`
Cancela um pedido **do próprio remetente**, e só enquanto ele está
`Pendente`. Requer token. `409` se o agente já reservou o pedido (o
cancelamento não pode ser falso — o papel sairia de qualquer forma), `404`
se o pedido não existe ou não é de quem pediu. O status vira `Cancelado`,
que fica **fora de todas as contagens** de consumo e relatórios.

---

## Rotas do agente

Exigem a `AGENTE_API_KEY`.

| Rota | Faz |
|---|---|
| `GET /api/agente/pendentes` | Lista os pedidos "Pendente", mais antigos primeiro, **em lote** (`ACALANTO_LOTE_AGENTE`, padrão 20) + `total_pendentes` |
| `GET /api/agente/arquivo/<id>` | Baixa o PDF (`application/pdf`). `410` se purgado |
| `POST /api/agente/status/<id>` | `{"status": "Imprimindo"\|"Concluído"\|"Erro", "detalhe"?}` — carimba o horário e registra na auditoria |
| `POST /api/agente/heartbeat` | Sinal de vida do agente (ver `/api/horario`) |

> **`Imprimindo` é uma RESERVA ATÔMICA.** O pedido só sai de `Pendente`
> uma vez: um segundo agente (o mesmo script esquecido em outra janela)
> recebe `409` e pula o pedido, em vez de imprimir a mesma coisa de novo.
> O agente **não deve imprimir** sem ter recebido `200` aqui.

> **`Imprimindo` é IDEMPOTENTE.** O agente manda um campo `reserva` (um
> identificador por tentativa). Repetir a chamada com o MESMO valor devolve
> `200` — sem isso, uma resposta perdida na rede fazia a retentativa
> receber `409`, o agente desistir, e o pedido congelar em "Imprimindo" sem
> nada ser impresso.

> **`Concluído`/`Erro` exigem o pedido reservado.** A rota recusa (`409`) se
> o pedido não estiver em `Imprimindo`, ou se a `reserva` for de outro
> agente — senão uma retentativa atrasada podia concluir um pedido que
> outro agente estava imprimindo, ou ressuscitar um pedido cancelado.

> **Pedido preso NÃO volta para a fila** — vira `Erro` com o motivo "confira
> na bandeja se o papel saiu". Um pedido preso está em estado
> **desconhecido**: o papel pode ter saído (o agente entregou ao spooler e
> perdeu a confirmação). Reenviar automaticamente resolveria metade dos
> casos e, na outra metade, faria a tiragem inteira sair de novo — a cada
> hora, enquanto a falha persistisse. Reimprimir é decisão de quem pode
> olhar a impressora. O corte é `ACALANTO_MINUTOS_PEDIDO_PRESO` (padrão
> 20), conferido na inicialização e a cada hora, com evento de ator
> `sistema`.

> **`detalhe` no `Erro`** é o motivo em português ("A impressora está sem
> papel") que a fila mostra ao professor. O agente **insiste** para
> confirmar o resultado: sem confirmação, o pedido volta a `Pendente` e
> seria impresso de novo.

> `Concluído` significa **entregue ao servidor de impressão sem travar na
> fila** — não "saiu no papel". O front-end exibe esse valor como "Enviado à
> impressora". O valor no banco foi mantido porque relatórios, cota e purga
> dependem dele.

---

## Relatórios

### `GET /api/relatorio`
Parâmetros: `tipo`, `data_inicio`, `data_fim` (`YYYY-MM-DD`), `professor`,
`segmento`, `formato` (`json` ou `csv`).

| `tipo` | Conteúdo | Quem acessa |
|---|---|---|
| `consumo` *(padrão)* | Impressões por professor | T.I., `COORDENACAO` (travado no próprio segmento) |
| `custos` | Cópias e impressões em P&B × Colorida, com quebra por professor | T.I., Diretor Administrativo |
| `materias` | Documentos agrupados por matéria (exclui envios da Diretoria) | T.I., Diretora Pedagógica |

Quem não tem permissão para aquele `tipo` recebe `401`.

`professor` filtra por nome exato (comparação sem diferenciar
maiúsculas/acentuação de caixa nem espaços nas pontas). `segmento` filtra por
`SEGMENTOS_VALIDOS`, mas é um **piso, nunca uma ampliação**: para uma
`COORDENACAO` de segmento, o valor pedido na query é **ignorado** — o servidor
sempre trava no(s) segmento(s) da própria sessão (a conta pode cobrir mais de
um). Só quem tem escopo `TUDO` (T.I., Diretoria, Coordenação Geral) pode de
fato escolher um segmento para estreitar a visão.

A resposta JSON sempre traz um bloco `filtros` refletindo o que foi
**realmente aplicado** (útil para o front saber se o segmento veio travado):
```json
{ "filtros": { "professor": null, "segmento": "FUND1", "segmentos": ["FUND1"], "segmento_rotulo": "Fundamental I", "segmento_travado": true }, "...": "..." }
```
`segmentos` lista **todos** os segmentos aplicados e `segmento_rotulo` já vem
juntado para exibição. `segmento` (único) fica preenchido só quando o filtro
cobre exatamente um segmento — com vários, vem `null`.
`consumo` e `materias` também trazem `professores_disponiveis`: os nomes
distintos do período dentro do escopo, antes do filtro por professor — é o
que alimenta o dropdown do front sem precisar de uma rota extra (`custos`
devolve o mesmo campo dentro do objeto espalhado por `**dados`).

No formato `csv`, o arquivo ganha uma primeira linha com os filtros aplicados
e o nome do arquivo passa a incluir professor/segmento (sanitizados, sem
acento/espaço) — a planilha circula fora do sistema e precisa ser
autoexplicativa sozinha.

### `GET /api/relatorio/documento/<id>`
Devolve o PDF do pedido para conferência. Restrito a quem tem escopo `TUDO`
(**T.I.**, **Diretora Pedagógica**, Coordenação Geral) ou, para uma
`COORDENACAO` de segmento, aos pedidos do **próprio segmento**. O **Diretor
Administrativo nunca tem acesso** — mesmo enxergando a fila inteira, abrir
documento é uma permissão à parte. `410` se o arquivo já tiver sido purgado
pela retenção.

### `GET /api/pedido/<id>/eventos`
Trilha de auditoria completa do pedido — quem fez o quê e quando. Restrito ao
**T.I.**. Útil para investigar "o que aconteceu com esse pedido".

```json
{ "pedido_id": 43, "eventos": [
  { "evento": "Pedido criado", "ator": "Marina Costa", "detalhe": "32 cópia(s); 2 pág.; …", "criado_em": "…" },
  { "evento": "Status: Imprimindo", "ator": "agente", "detalhe": "de 'Pendente' para 'Imprimindo'", "criado_em": "…" }
]}
```

---

## Gestão de usuários

Todas restritas ao cargo **T.I.**

| Rota | Faz |
|---|---|
| `GET /api/admin/usuarios` | Lista as contas locais (sem senha), com `segmento` (texto cru) e `segmentos` (lista) |
| `POST /api/admin/usuarios` | Cria conta: `{name, username, password, role, segmentos?}` (ou `segmento`) |
| `POST /api/admin/usuarios/<username>/role` | Define o cargo: `{role}` |
| `POST /api/admin/usuarios/<username>/segmento` | Define o(s) segmento(s): `{segmentos: [...]}` ou `{segmento}` (lista vazia/`""` limpa) |
| `POST /api/admin/usuarios/<username>/senha` | Redefine a senha: `{password}` |
| `POST /api/admin/usuarios/<username>/remover` | Remove a conta |

Cargos válidos: `COORDENADOR`, `COORDENACAO`, `DIRETOR_ADM`, `DIRETORA_PED`,
`TI`. Segmentos válidos: `INFANTIL`, `FUND1`, `FUND2`, `GERAL`.

> ARMADILHA DE NOME: `COORDENADOR` (professor comum, só vê o que é seu) e
> `COORDENACAO` (coordenadora de segmento, supervisiona) são cargos
> diferentes — os nomes parecidos são de propósito, é assim que o colégio
> chama os dois. O valor `COORDENADOR` já está gravado em contas reais e não
> muda.
>
> Para um `COORDENADOR`, o segmento só pré-preenche o formulário de envio
> (sem efeito de permissão). Para uma `COORDENACAO`, o segmento **define o
> escopo de visão** — ver `escopo_de_visao()` em `app.py`.
>
> Uma conta pode ter **vários** segmentos (coordenador de área que dá aula em
> dois, coordenação que cobre dois): a coluna guarda os códigos separados por
> vírgula (`"FUND1,FUND2"`), e a `COORDENACAO` passa a enxergar os pedidos de
> todos eles.

**Proteções:** ninguém altera ou remove a própria conta por estas rotas, e um
T.I. comum não pode mexer numa conta `super_admin`.

---

## Testando pelo terminal

```powershell
# 1. Login — guarde o token
$r = Invoke-RestMethod -Uri http://localhost:8080/api/login -Method Post `
     -ContentType 'application/json' `
     -Body '{"username":"admin","password":"SUA_SENHA"}'
$h = @{ Authorization = "Bearer $($r.token)" }

# 2. Consultar a fila
Invoke-RestMethod -Uri http://localhost:8080/api/fila -Headers $h

# 3. Auditoria de um pedido
Invoke-RestMethod -Uri http://localhost:8080/api/pedido/43/eventos -Headers $h

# 4. Testar a chave do agente
Invoke-RestMethod -Uri http://localhost:8080/api/agente/pendentes `
     -Headers @{ Authorization = "Bearer SUA_AGENTE_API_KEY" }
```
