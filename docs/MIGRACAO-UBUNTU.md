# Migração do servidor para uma VM Ubuntu

Roteiro para tirar o **servidor** do Windows e colocá-lo numa VM Ubuntu.
O **agente continua no PC da impressora** — não há como movê-lo (explicação
em [O que vai e o que fica](#o-que-vai-e-o-que-fica)).

> **A VM adotada foi Windows** — o roteiro em uso é
> [MIGRACAO-VM-WINDOWS.md](MIGRACAO-VM-WINDOWS.md). Este documento fica como
> o caminho alternativo: a aplicação é a mesma nos dois, muda só a forma de
> manter o serviço de pé (systemd/nginx aqui, tarefa agendada lá).

Tempo estimado: **1h30**, sendo ~20 min de indisponibilidade real (o
trecho entre parar o servidor antigo e subir o novo). Faça fora do horário
de aula.

---

## O que vai e o que fica

| Componente | Onde fica depois | Por quê |
|---|---|---|
| `app.py`, `banco_dados/`, tela compilada | **VM Ubuntu** | Python/Flask/SQLite puro — nenhuma linha executável depende do Windows |
| `agente_impressao.py`, `automacao_impressora.py` | **PC da impressora (Windows)** | É quem fala com a Konica: lê o registro do Windows, consulta as filas (`Get-Printer`) e dispara o `SumatraPDF.exe` |

O sistema já foi desenhado para essa separação — a variável `CLOUD_URL` do
agente existe exatamente para o servidor morar em outro lugar.

> **O que muda na prática:** hoje servidor e agente estão na mesma máquina,
> então a rede entre eles nunca falha. Separados, ela passa a poder falhar.
> As proteções para isso já existem (reserva idempotente, confirmação com
> retentativa, pedido preso virando "Erro" em vez de reimprimir, sinal de
> vida do agente) — mas é por isso que o **aviso de "impressora fora do ar"
> na tela passa a ser o seu alarme principal**.

---

## As três camadas (e o que o nginx NÃO faz)

Vale desfazer uma confusão comum antes de instalar qualquer coisa:

| Camada | O que é | Substituível? |
|---|---|---|
| **Flask** (`app.py`) | A **aplicação**: rotas, permissões, validação do PDF | **Não** — é o sistema |
| **waitress** | O **servidor HTTP**: abre a porta e fala HTTP | Sim (gunicorn, uWSGI) |
| **nginx** | **Proxy reverso**: HTTPS, limite de upload, porta fechada | Opcional |

**O Flask não é o servidor** — é o código. E **nginx não executa Python**:
ele recebe a requisição e repassa para o waitress, que roda a aplicação.
Ou seja, o nginx não elimina uma camada, acrescenta uma.

> **O sistema não depende de nginx nem de IIS.** O waitress abre a porta e
> serve tudo (a tela e a API) sozinho — é assim que já funciona no Windows.
> O IIS, aliás, nunca esteve envolvido: ele não executa Python.

### Com nginx ou sem nginx

| | Com nginx *(padrão)* | Sem nginx |
|---|---|---|
| Instalar | `sudo bash instalar.sh` | `sudo COM_NGINX=nao bash instalar.sh` |
| Endereço | `http://impressao.exemplo.com.br` | `http://192.168.0.50:8080` |
| HTTPS | Possível (passo 9) | **Não** — o waitress não faz TLS |
| Porta 8080 | Fechada para a rede | Aberta (é por onde se acessa) |
| Peças para manter | duas | uma |

Sem nginx funciona bem e é uma escolha legítima para rede interna — é
exatamente o arranjo de hoje no Windows. Você só perde o caminho para o
HTTPS, e ganha uma peça a menos para manter.

Se quiser o endereço limpo (sem `:8080`) e ainda assim sem nginx, instale
com `ACALANTO_PORT=80`: o instalador concede ao serviço apenas a permissão
de abrir porta baixa (`CAP_NET_BIND_SERVICE`), sem precisar rodá-lo como
root.

```bash
sudo COM_NGINX=nao ACALANTO_PORT=80 bash instalar.sh
```

### Por que não trocar waitress por gunicorn

O gunicorn é o caminho idiomático em Linux, mas roda **vários processos** —
e três coisas neste sistema dependem de haver **um só**:

1. O **limite de tentativas de login** vive na memória do processo: com 4
   workers, cada um teria seu contador e o limite de 5 viraria 20.
2. A **rotina de manutenção** (que sinaliza pedidos presos) roda numa
   thread: seriam 4 reapers concorrendo no mesmo banco.
3. **SQLite** com várias escritas simultâneas aumenta a disputa por lock —
   justo o que o WAL veio reduzir.

O waitress usa *threads* dentro de um processo, que é o modelo certo aqui,
e mantém Windows e Linux idênticos — se precisar voltar atrás, o caminho é
simétrico.

---

## Antes de começar

- [ ] VM **Ubuntu 24.04 LTS** criada, com IP fixo na rede do colégio
- [ ] Acesso `sudo` na VM
- [ ] A VM alcança o PC da impressora e vice-versa (`ping` nos dois sentidos)
- [ ] Porta **80** liberada na VM (e 8080 **não** precisa ficar exposta)
- [ ] Disco com folga: o banco já está em ~190 MB e cresce com os PDFs
      (20 GB sobram; e vale ligar `ACALANTO_RETENCAO_DIAS` na migração)
- [ ] Combinar a janela de parada com a escola

### Particularidades do Ubuntu 24.04

- **Python 3.12** já vem instalado — atende de sobra (o projeto precisa de
  3.9+ por causa do `zoneinfo`).
- **PEP 668:** desde o 24.04 o Python do sistema é "externally managed" e
  `pip install` fora de um ambiente virtual falha com
  `error: externally-managed-environment`. O instalador já cria o `.venv`,
  então isso não aparece — mas se você instalar algo à mão, lembre de usar
  `/opt/acalanto/.venv/bin/pip`, nunca o `pip` do sistema.
- **systemd 255** — as units do pacote já seguem o formato atual
  (`StartLimit*` na seção `[Unit]`).

---

## Rodada de teste (antes da migração de verdade)

Vale subir a VM em paralelo, com o Windows ainda atendendo, só para ver o
sistema de pé no Linux. Para isso funcionar sem estragar nada:

**Use uma CÓPIA do banco, não o de produção.** Pode copiar com o servidor
Windows no ar (é só teste — se faltarem os últimos minutos, não importa):

```powershell
scp banco_dados\acalanto_print.db usuario@192.168.0.50:/tmp/
```

**Não aponte o agente para a VM ainda.** Enquanto o `agente.env` continuar
apontando para o Windows, a VM fica isolada: você pode entrar, navegar e
conferir os relatórios sem tocar em nada real.

**Não divulgue o endereço da VM.** Este é o ponto que merece atenção: um
pedido enviado pela VM de teste fica no banco DELA e **ninguém imprime** —
não há agente escutando. A professora veria "na fila" para sempre. Se
alguém precisar testar o envio de verdade, combine antes e aponte o agente
temporariamente.

**O que dá para validar sem agente:** login, navegação, fila (dados
copiados), relatórios, download de CSV, painel de usuários, e o aviso de
"impressora fora do ar" — que, aliás, **deve** aparecer, já que nenhum
agente está falando com essa VM. É sinal de que o alarme funciona.

Quando terminar o teste, é só apagar o banco de teste e seguir o roteiro
abaixo do começo, agora com a cópia boa:

```bash
sudo systemctl stop acalanto
sudo rm /opt/acalanto/banco_dados/acalanto_print.db
```

---

## 1. Preparar o código no Windows

Gere a tela compilada — é ela que o servidor vai servir:

```powershell
cd Front-end
npm run build
```

Confirme que `Front-end/dist/index.html` existe. Sem isso, a VM sobe só a
API e os professores veem uma resposta em JSON em vez do sistema.

## 2. Medir o banco (para dimensionar a janela)

```powershell
.\.venv\Scripts\python.exe deploy\conferir_banco.py
```

Diz quantos pedidos existem e quanto o arquivo pesa — é o que permite estimar
quanto tempo a cópia do passo 5 vai levar.

> **Esta saída não é a que você vai comparar no fim.** O servidor segue no ar
> durante os passos 3 e 4, e os professores seguem enviando PDFs: o banco
> legitimamente cresce nesse meio-tempo. A radiografia que vale é tirada no
> passo 5, com o servidor **já parado**. Comparar contra esta daria
> divergência sempre — e o roteiro mandaria você recopiar 190 MB atrás de um
> problema que não existe.

## 3. Copiar o projeto para a VM e instalar

Do Windows (ajuste o IP e o usuário):

```powershell
scp -r . usuario@192.168.0.50:/tmp/acalanto-origem
```

Na VM:

```bash
sudo bash /tmp/acalanto-origem/deploy/ubuntu/instalar.sh
```

O script instala os pacotes (inclusive **tzdata**, sem o qual todos os
horários quebram), cria o usuário de sistema `acalanto`, monta o ambiente
virtual, instala as dependências e prepara systemd e nginx. Pode rodar de
novo quando quiser: ele **nunca** sobrescreve o `.env` nem o banco.

## 4. Gerar chaves novas

A migração é o momento certo para rotacionar os segredos — as chaves atuais
estão no histórico do Git e devem ser consideradas comprometidas.

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"   # rode duas vezes
sudo nano /opt/acalanto/.env
```

Preencha `ACALANTO_SECRET_KEY` (uma) e `AGENTE_API_KEY` (a outra). Guarde a
segunda: ela precisa ser **idêntica** no `agente.env` do PC da impressora.

> Trocar `ACALANTO_SECRET_KEY` derruba todas as sessões abertas — o que é
> justamente o desejado numa migração.

Aproveite e revise, no mesmo arquivo:

```bash
ACALANTO_AUTOCADASTRO=fechado    # recomendado: contas passam a ser criadas pelo T.I.
ACALANTO_RETENCAO_DIAS=180       # descarta o PDF antigo, mantendo o registro
HORARIO_INICIO_IMPRESSAO=07:00   # os MESMOS valores do agente.env
HORARIO_FIM_IMPRESSAO=19:00
```

## 5. Parar o servidor antigo e copiar o banco

**A partir daqui começa a indisponibilidade.** No Windows, feche a janela do
`app.py` (Ctrl+C) — e confirme que ninguém está enviando.

> **Não copie o `.db` com o servidor no ar.** Desde que o WAL foi ligado, o
> banco são três arquivos (`.db`, `.db-wal`, `.db-shm`) e copiar só o
> primeiro pode deixar de fora os últimos pedidos. Com o servidor parado, o
> WAL é consolidado no fechamento e o `.db` basta.

Com o servidor **já parado**, tire agora a radiografia que vale:

```powershell
.\.venv\Scripts\python.exe deploy\conferir_banco.py > banco-antes.txt
```

Copie:

```powershell
scp banco_dados\acalanto_print.db usuario@192.168.0.50:/tmp/
```

Na VM:

```bash
sudo mv /tmp/acalanto_print.db /opt/acalanto/banco_dados/
sudo chown acalanto:acalanto /opt/acalanto/banco_dados/acalanto_print.db
sudo chmod 600 /opt/acalanto/banco_dados/acalanto_print.db
sudo -u acalanto /opt/acalanto/.venv/bin/python \
     /opt/acalanto/deploy/conferir_banco.py
```

**Compare com o `banco-antes.txt` que você acabou de gerar.** Como o servidor
estava parado nas duas medições, contagens, somas e o hash dos PDFs **têm**
que bater exatamente. Se divergir, a cópia falhou de verdade: recopie — não
suba o sistema em cima de um banco incompleto.

## 6. Subir o sistema

```bash
sudo systemctl enable --now acalanto
sudo systemctl enable --now acalanto-backup.timer
sudo systemctl reload nginx

systemctl status acalanto
curl -s http://localhost/api/horario | head -c 300
```

A resposta do `curl` deve trazer o horário e o estado do agente. Abra
`http://192.168.0.50/` no navegador: a tela de login precisa aparecer.

## 6b. Apontar o nome no DNS

O endereço combinado é **`impressao.exemplo.com.br`** → **`192.168.0.50`**.
Crie o registro `A` no DNS que a rede do colégio usa. Duas formas, conforme
onde o DNS é resolvido:

- **DNS interno** (servidor do colégio, controlador de domínio): registro `A`
  apontando para `192.168.0.50`. É o mais comum e resolve só de dentro.
- **DNS público** (onde o `exemplo.com.br` é hospedado): também
  funciona — um registro público pode apontar para um IP privado. De fora
  ninguém alcança (192.168.x.x não é roteável na internet), e de dentro
  resolve normalmente. É esse o caminho se você quiser o certificado do
  passo 9.

Conferir, de uma máquina da rede:

```powershell
nslookup impressao.exemplo.com.br
```

Deve responder `192.168.0.50`. O nginx já está configurado para atender pelos
dois — nome e IP —, então o sistema funciona antes mesmo do DNS ficar pronto.

## 7. Apontar o agente para a VM

No **PC da impressora**, edite o `agente.env`:

```bash
CLOUD_URL=http://192.168.0.50
AGENTE_API_KEY=<a MESMA chave do passo 4>
```

Reinicie o agente. No console dele:

```
[Agente] Iniciado. Consultando http://192.168.0.50 a cada 15s.
[Agente] Horário de impressão: 07:00–19:00.
```

> **A ordem importa.** Atualize o **agente primeiro** quando houver versão
> nova, depois o servidor. E confira que a faixa de horário é a mesma dos
> dois lados: é o servidor que promete o horário ao professor e o agente que
> o cumpre.

## 8. Teste de ponta a ponta

- [ ] Entrar com uma conta de professor
- [ ] Enviar um PDF de 1 página, 1 cópia — **conferir se o papel sai**
- [ ] A fila mostra o pedido como "Enviado à impressora"
- [ ] O painel lateral **não** mostra "impressora fora do ar"
- [ ] Baixar um CSV em Relatórios (valida o caminho de download pelo nginx)
- [ ] Enviar um PDF grande (20–40 MB) — valida o `client_max_body_size`
- [ ] `journalctl -u acalanto -n 50` sem erros

Só depois disso avise os professores.

---

## 9. (Opcional) HTTPS com certificado de verdade

Como `impressao.exemplo.com.br` é um domínio que o colégio controla,
dá para ter um certificado **Let's Encrypt legítimo** — sem aviso de "site
não seguro" e sem configuração extra no agente. Isso normalmente não seria
possível num servidor só de rede interna, e a saída é o desafio **DNS-01**:
o Let's Encrypt valida o domínio por um registro TXT, sem precisar alcançar
a VM pela internet (192.168.0.50 é privado e não é roteável).

```bash
sudo apt install certbot
sudo certbot certonly --manual --preferred-challenges dns \
     -d impressao.exemplo.com.br
```

O certbot pede para criar um TXT `_acme-challenge.impressao...` no DNS do
domínio. Emitido o certificado, descomente o bloco HTTPS em
`/etc/nginx/sites-available/acalanto`, troque o conteúdo do bloco da porta
80 por `return 301 https://$host$request_uri;` e recarregue o nginx.

> **Antes de decidir:** no modo `--manual` a renovação (a cada 90 dias) é
> manual, e **certificado vencido derruba o acesso de todo mundo**. Se o
> DNS do colégio estiver num provedor com plugin do certbot (Cloudflare,
> Route53 e outros), a renovação fica automática e aí vale muito a pena.
> Senão, HTTP na rede interna é uma escolha defensável — é o que já se usa
> hoje — desde que ninguém acesse de fora.

> **Ao migrar para HTTPS, atualize o agente** no mesmo dia:
> `CLOUD_URL=https://impressao.exemplo.com.br` no `agente.env`.

---

## Depois da migração

**O endereço mudou.** Os professores acessavam o IP do PC antigo; agora é
`http://impressao.exemplo.com.br` (ou `http://192.168.0.50`) — e sem
`:5173` nem `:8080`, porque a tela e a API saem pela mesma porta. Vale um
aviso à equipe e atualizar os favoritos das máquinas do laboratório.

**Backup automático** roda às 02:30 e guarda 14 dias em
`/var/backups/acalanto`. Confira de vez em quando:

```bash
systemctl list-timers acalanto-backup
ls -lh /var/backups/acalanto
```

Restaurar é copiar o `.gz`, descompactar e pôr no lugar do `.db` com o
serviço parado.

**Atualizar o sistema depois:**

```bash
# do Windows, com o build novo já gerado
scp -r . usuario@192.168.0.50:/tmp/acalanto-origem
# na VM
sudo bash /tmp/acalanto-origem/deploy/ubuntu/instalar.sh
sudo systemctl restart acalanto
```

O `.env` e o banco são preservados pelo instalador.

---

## Se algo der errado

| Sintoma | Onde olhar |
|---|---|
| Serviço não sobe | `journalctl -u acalanto -n 100` — quase sempre é chave faltando no `.env` |
| "413" ao enviar PDF | `client_max_body_size` no nginx (deve ser 55M) |
| Todo mundo bloqueado no login ao mesmo tempo | Falta `ACALANTO_ATRAS_DE_PROXY=true` no `.env` — sem isso, todos chegam como 127.0.0.1 |
| Horários errados por 3h | `tzdata` ausente na VM (`sudo apt install tzdata`) |
| "Read-only file system" no log | Falta um caminho em `ReadWritePaths` na unit do systemd |
| Agente diz "Não autorizado" | `AGENTE_API_KEY` diferente entre `.env` da VM e `agente.env` do PC |
| Tela mostra "impressora fora do ar" | O agente não alcança a VM: confira `CLOUD_URL`, firewall e se o agente está rodando |
| Tela em JSON em vez do sistema | Faltou o `npm run build` (passo 1) — não existe `Front-end/dist` |
| Tela abre, mas login/fila não respondem | Build do front antigo (anterior a esta migração), que ainda chama a porta 8080. Rode `npm run build` de novo e recopie |
| O nome não abre, mas o IP sim | Falta o registro `A` no DNS (passo 6b) |

**Voltar atrás** é simples, e vale a pena saber disso antes de começar: o
Windows continua com tudo instalado. Basta parar o serviço na VM
(`sudo systemctl stop acalanto`), repor o `CLOUD_URL` antigo no
`agente.env` (ou removê-lo, que volta para `localhost`) e rodar `py app.py`
no Windows. O único cuidado é o banco: os pedidos criados na VM ficam lá.
Por isso a janela de teste do passo 8 deve ser curta e sem professores
enviando.
