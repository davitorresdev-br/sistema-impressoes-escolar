# Migração do servidor para uma VM Windows

Roteiro para tirar o **servidor** do PC atual e colocá-lo numa VM Windows,
com ele subindo sozinho junto com a máquina.

> Se um dia a escolha mudar para Linux, o roteiro equivalente está em
> [MIGRACAO-UBUNTU.md](MIGRACAO-UBUNTU.md). O código é o mesmo nos dois —
> muda só a forma de manter o serviço de pé.

Tempo estimado: **1h**, sendo ~20 min de indisponibilidade real. Faça fora
do horário de aula.

---

## O que vai e o que fica

| Componente | Onde fica | Por quê |
|---|---|---|
| `app.py`, `banco_dados/`, tela compilada | **VM Windows** | É o servidor |
| `agente_impressao.py`, `automacao_impressora.py` | **PC da impressora** | É quem fala com a Konica |

O sistema **não depende de IIS nem de nginx**: o waitress abre a porta e
serve a tela e a API sozinho. Numa VM Windows não há proxy nenhum no
caminho — é o arranjo mais simples possível.

> **O que muda na prática:** hoje servidor e agente estão na mesma máquina,
> então a rede entre eles nunca falha. Separados, ela passa a poder falhar.
> As proteções já existem (reserva idempotente, confirmação com
> retentativa, pedido preso virando "Erro" em vez de reimprimir) — mas o
> aviso de **"impressora fora do ar"** na tela passa a ser o seu alarme.

### E se o agente também for para a VM?

Como a VM é Windows, isso passa a ser **possível** — as filas da Konica são
compartilhadas (`\\SERVIDOR\Impressora ...`), e uma VM Windows pode se
conectar a elas pela rede. Consolidaria tudo numa máquina só e eliminaria a
rede entre servidor e agente.

Três coisas a saber antes de tentar:

1. **A tarefa do agente NÃO pode rodar como SISTEMA.** As conexões de
   impressora são por usuário (o código lê `HKEY_CURRENT_USER`), então ela
   precisa rodar com uma conta que tenha as filas mapeadas, marcando
   "executar estando o usuário conectado ou não".
2. **O SumatraPDF precisa imprimir a partir da VM** — é o que garante que
   cor, frente e verso e grampo continuam saindo certo.
3. **Valide imprimindo de verdade** antes de desligar o agente do PC atual.

Recomendação: faça a migração do servidor primeiro, com o agente onde está.
Mover o agente é um segundo passo, independente — e o caminho de impressão
está funcionando hoje, então não vale mexer nos dois ao mesmo tempo.

---

## Antes de começar

- [ ] VM Windows criada, com **IP fixo** (192.168.0.50) na rede do colégio
- [ ] Acesso de **administrador** na VM
- [x] **Licença** — a VM do colégio não tem prazo para expirar (confirmado
      com a T.I. em 24/09/2026). O quadro abaixo fica só para referência, caso
      um dia alguém suba uma VM a partir de mídia de avaliação
- [ ] **Python instalado na VM.** Use a **mesma versão que o PC atual roda**
      (`py --version` lá; hoje é 3.14.6) — igualar as duas máquinas elimina o
      "funciona aqui e quebra lá". O mínimo do projeto é 3.9, por causa do
      `zoneinfo`. Baixe de [python.org](https://www.python.org/downloads/windows/)
      o *Windows installer (64-bit)*.

      Numa VM, o caminho mais curto é baixar no seu PC e instalar em silêncio
      (o Windows Server bloqueia download pelo navegador, via *IE Enhanced
      Security*):

      ```powershell
      C:\python-3.14.6-amd64.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
      ```

      `InstallAllUsers=1` importa: o servidor roda como **SYSTEM**.
      `PrependPath=1` é o "Add python.exe to PATH" que o instalador procura.
      Depois, abra uma janela **nova** do PowerShell — a atual não enxerga o
      PATH novo.
- [ ] **A VM alcança a internet.** O passo 4 baixa as dependências do PyPI. Se
      a rede tiver proxy ou inspeção de TLS, resolva isso antes — no meio da
      janela de parada é o pior momento para descobrir
- [ ] A VM alcança o PC da impressora e vice-versa (`ping` nos dois sentidos)
- [ ] **Fuso horário da VM** conferido em *Settings → Time & Language*. Não
      afeta o horário de impressão (o código fixa `America/Sao_Paulo`), mas o
      backup diário roda no fuso da máquina — com a VM em UTC ele cairia às
      23:30, dentro do expediente
- [ ] Disco: reserve **~10 GB** só para os dados. O banco está em 190 MB e
      quase não comprime; são 14 backups diários (~2,5 GB) mais o banco, mais
      o crescimento dos PDFs
- [ ] Combinar a janela de parada com a escola

### A licença de avaliação *(não se aplica à nossa VM — referência)*

Se o rodapé da área de trabalho disser **"Evaluation"** com uma contagem de
dias, essa VM tem prazo. Quando a avaliação expira, o Windows Server passa a
**desligar sozinho a cada hora** — não é um aviso, é o comportamento.

Confira:

```powershell
DISM /online /Get-CurrentEdition
```

`ServerStandardEval` confirma a avaliação. Dá para converter em definitiva
com a VM já em produção, sem reinstalar (pede um reboot):

```powershell
DISM /online /Set-Edition:ServerStandard /ProductKey:XXXXX-XXXXX-XXXXX-XXXXX-XXXXX /AcceptEula
```

Vale resolver **agora**, com a VM vazia: depois que a escola depender dela, o
reboot da conversão vira uma segunda janela de indisponibilidade.

### A porta: 80 ou 8080?

No Windows não existe a restrição de "porta privilegiada" do Linux, então
as duas funcionam sem cerimônia. A diferença é só o endereço:

| Porta | Endereço | Observação |
|---|---|---|
| **8080** | `http://192.168.0.50:8080` | Mesma de hoje — uma variável a menos no teste |
| **80** | `http://impressao.exemplo.com.br` | Sem porta no endereço; **confira se está livre** |

Antes de escolher a 80, veja se algo já a ocupa (o IIS costuma vir
instalado em Windows Server e reserva a 80):

```powershell
netstat -ano | findstr ":80 "
```

Se aparecer algo, ou use a 8080 ou desative o serviço que a ocupa
(`Stop-Service W3SVC; Set-Service W3SVC -StartupType Disabled`).

---

## Rodada de teste (antes da migração de verdade)

**Faça isto primeiro.** Os passos 1 a 5 e 7 podem ser feitos com o servidor
atual ainda atendendo normalmente, **sem parar ninguém**. Você vê o sistema
de pé na VM, descobre os problemas do ambiente com calma, e só depois marca
a janela — que fica reduzida a parar, copiar o banco e apontar o agente.

Três cuidados para o ensaio não estragar nada:

**Use uma CÓPIA do banco, não o de produção.** Pode copiar com o servidor
no ar; é só teste, se faltarem os últimos minutos não importa:

```powershell
Copy-Item banco_dados\acalanto_print.db \\192.168.0.50\c$\acalanto\banco_dados\
```

**Não aponte o agente para a VM ainda.** Enquanto o `agente.env` continuar
apontando para o servidor atual, a VM fica isolada: dá para entrar, navegar
e conferir relatórios sem tocar em nada real.

**Não divulgue o endereço da VM.** É o ponto que mais merece atenção: um
pedido enviado pela VM de teste fica no banco *dela* e **ninguém imprime** —
não há agente escutando. A professora veria "na fila" para sempre.

**O que dá para validar sem agente:** login, navegação, fila (com os dados
copiados), relatórios, download de CSV, painel de usuários, o reinício
automático da VM, e o aviso de **"impressora fora do ar"** — que, aliás,
*deve* aparecer, já que nenhum agente está falando com essa VM. É sinal de
que o alarme funciona.

Quando for fazer a migração de verdade, o banco de teste é substituído pelo
de produção no passo 6.

---

## 1. Preparar o código no PC atual

```powershell
npm --prefix Front-end run build
```

Confirme que `Front-end\dist\index.html` existe. Sem isso a VM sobe só a
API e os professores veem JSON em vez do sistema.

> O `--prefix` evita dois tropeços: ele **não muda a pasta atual** (o passo 3
> precisa que você esteja na raiz do projeto), e dispensa encadear comandos —
> o `&&` não existe no Windows PowerShell 5.1, só no PowerShell 7.

> O build precisa ser **recente**: versões anteriores a esta migração
> fixavam a porta 8080 na chamada da API e não funcionariam pelo endereço
> novo.

## 2. Medir o banco (para dimensionar a janela)

```powershell
.\.venv\Scripts\python.exe deploy\conferir_banco.py
```

Diz quantos pedidos existem e quanto o arquivo pesa — é o que permite estimar
quanto tempo a cópia do passo 6 vai levar.

> **Esta saída não é a que você vai comparar no fim.** O servidor segue no ar
> durante os passos 3, 4 e 5, e os professores seguem enviando PDFs: meia hora
> depois o banco legitimamente tem mais pedidos. A radiografia que vale é
> tirada no passo 6, com o servidor **já parado**. Comparar contra esta daria
> divergência sempre — e o roteiro mandaria você recopiar 190 MB atrás de um
> problema que não existe.

## 3. Copiar o projeto para a VM

Copie a pasta do projeto para um caminho estável na VM — sugestão:
**`C:\acalanto`**. Pode ser por pendrive, pasta compartilhada ou, da pasta
do projeto:

```powershell
robocopy . \\192.168.0.50\c$\acalanto /E /XD .git .venv node_modules __pycache__ logs temp_impressao backups /XF .env agente.env *.log *.db *.db-wal *.db-shm
```

O `/XD` e o `/XF` são o que deixa de fora: o instalador recria o `.venv`, e
o banco e as chaves vêm nos passos seguintes. Use `robocopy` e não
`Copy-Item`: o `-Exclude` do `Copy-Item` não funciona de forma confiável
com `-Recurse`, e viria tudo junto.

> O robocopy termina com **código 1** quando copiou arquivos — isso é
> sucesso, não erro. Só a partir de **8** é falha de verdade.

**Confira que o `Front-end\dist` chegou.** Ele não está no Git (é gerado),
então não vem num `git clone` — só na cópia do passo 1.

## 4. Instalar

Na VM, **PowerShell como Administrador**:

```powershell
cd C:\acalanto
powershell -ExecutionPolicy Bypass -File deploy\windows\instalar.ps1 -Porta 8080
```

O que ele faz: confere o Python, cria o `.venv`, instala as dependências,
roda um **teste de fumaça** (importa tudo o que o servidor precisa e resolve
o fuso de São Paulo), cria o `.env` a partir do exemplo, libera a porta no
Firewall, mostra o perfil de rede da VM e registra **duas tarefas
agendadas** — o servidor (inicia com a máquina, reinicia se cair) e o backup
diário.

Se qualquer etapa falhar, ele **para ali e não registra nada**. Isso é de
propósito: um instalador que anuncia sucesso sobre um ambiente quebrado
empurra o problema para o meio da janela de parada, onde ele custa caro.

Pode rodar de novo quando quiser: **nunca** sobrescreve o `.env` nem o banco.

## 5. Gerar chaves novas

A migração é o momento certo para rotacionar os segredos — as chaves atuais
estão no histórico do Git e devem ser consideradas comprometidas.

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Rode duas vezes e preencha no `C:\acalanto\.env`:

```
ACALANTO_SECRET_KEY=<a primeira>
AGENTE_API_KEY=<a segunda>
```

Guarde a segunda: ela precisa ser **idêntica** no `agente.env` do PC da
impressora.

Aproveite e revise, no mesmo arquivo:

```
ACALANTO_AUTOCADASTRO=fechado    # contas passam a ser criadas pelo T.I.
ACALANTO_RETENCAO_DIAS=180       # descarta o PDF antigo, mantendo o registro
HORARIO_INICIO_IMPRESSAO=07:00   # os MESMOS valores do agente.env
HORARIO_FIM_IMPRESSAO=19:00
```

## 6. Parar o servidor antigo, radiografar e copiar o banco

**A partir daqui começa a indisponibilidade.** No PC atual, feche a janela
do `app.py` (Ctrl+C) e confirme que ninguém está enviando.

> **Não copie o `.db` com o servidor no ar.** Desde que o WAL foi ligado, o
> banco são três arquivos (`.db`, `.db-wal`, `.db-shm`) e copiar só o
> primeiro pode deixar de fora os últimos pedidos. Parado, o WAL é
> consolidado no fechamento e o `.db` basta.

Com o servidor **já parado**, tire agora a radiografia que vale:

```powershell
.\.venv\Scripts\python.exe deploy\conferir_banco.py > banco-antes.txt
```

Copie o banco:

```powershell
Copy-Item banco_dados\acalanto_print.db \\192.168.0.50\c$\acalanto\banco_dados\
```

Na VM, tire a mesma radiografia:

```powershell
cd C:\acalanto
.\.venv\Scripts\python.exe deploy\conferir_banco.py > banco-depois.txt
```

**Compare os dois arquivos.** Como o servidor estava parado nas duas
medições, agora as contagens, as somas e o hash dos PDFs **têm** que bater
exatamente. Se divergir, a cópia falhou de verdade: recopie — não suba o
sistema sobre um banco incompleto.

## 7. Subir o sistema

```powershell
Start-ScheduledTask -TaskName "Acalanto - Servidor de Impressao"
Start-Sleep 5
Get-ScheduledTask -TaskName "Acalanto - Servidor de Impressao" | Get-ScheduledTaskInfo
Invoke-RestMethod http://localhost:8080/api/horario
```

O `Invoke-RestMethod` deve trazer o horário e o estado do agente.

> **Esse teste sozinho não prova quase nada:** ele fala com a máquina por
> dentro e nem encosta no Firewall. O que vale é abrir
> `http://192.168.0.50:8080/` **de outra máquina** e ver a tela de login. Se
> responder por dentro mas não por fora, o problema é Firewall ou perfil de
> rede — não a aplicação.

Se algo falhar, o log está em `C:\acalanto\logs\servidor.log`.

> **E se o `servidor.log` não existir?** Então a aplicação morreu *antes* de
> abrir o log — em geral no import, por dependência faltando. Rode o
> instalador de novo: o teste de fumaça dele reprova exatamente esse caso e
> mostra a mensagem de verdade.

## 8. Apontar o nome no DNS *(feito por terceiros)*

> **Não faça este passo por conta própria.** O DNS do colégio é cuidado pelo
> sênior do departamento junto a uma empresa contratada — combinado em
> 24/09/2026. Peça o registro a eles.

O que pedir: o registro `A` **`impressao.exemplo.com.br` →
`192.168.0.50`**.

Vale dizer a quem for fazer que o caminho seguro é a zona **interna** do
`SERVIDOR`, e que ela precisa ser uma *zona de nome único* — uma zona
chamada exatamente `impressao.exemplo.com.br`, com um só registro na
raiz. Criar uma zona para `exemplo.com.br` inteiro faria o DNS interno
se considerar autoritativo pelo domínio todo, e o site e o e-mail parariam de
resolver dentro da escola.

Se optarem pela zona **pública**, também funciona — mas só de dentro da rede,
e alguns navegadores recusam nome público que resolve para IP privado
(proteção contra *DNS rebinding*).

Confira de outra máquina:

```powershell
nslookup impressao.exemplo.com.br
```

Com a porta 8080, o endereço fica
`http://impressao.exemplo.com.br:8080`.

## 9. Apontar o agente para a VM

No **PC da impressora**, edite o `agente.env`:

```
CLOUD_URL=http://192.168.0.50:8080
AGENTE_API_KEY=<a MESMA chave do passo 5>
```

Reinicie o agente. No console dele:

```
2026-09-23 14:02:11,431 [INFO] Agente iniciado. Consultando http://192.168.0.50:8080 a cada 15s.
2026-09-23 14:02:11,522 [INFO] Horário de impressão: das 07:00 às 19:00.
```

(As mesmas linhas ficam gravadas em `agente.log`, ao lado do script.)

> **A ordem importa** em atualizações futuras: agente primeiro, servidor
> depois. E a faixa de horário precisa ser a mesma dos dois lados — é o
> servidor que promete o horário ao professor e o agente que o cumpre.

## 10. Teste de ponta a ponta

- [ ] Entrar com uma conta de professor
- [ ] Enviar um PDF de 1 página, 1 cópia — **conferir se o papel sai**
- [ ] A fila mostra o pedido como "Enviado à impressora"
- [ ] O painel lateral **não** mostra "impressora fora do ar"
- [ ] Baixar um CSV em Relatórios
- [ ] Enviar um PDF grande (20–40 MB)
- [ ] **Reiniciar a VM** e confirmar que o sistema volta sozinho
- [ ] `logs\servidor.log` sem erros

O teste de reinício é o que prova o ganho da migração — é exatamente o que
não acontecia antes.

---

## Depois da migração

**O endereço mudou.** Avise a equipe e atualize os favoritos das máquinas.

**Backup automático** roda às 02:30 e guarda 14 dias em `C:\acalanto\backups`:

```powershell
Get-ScheduledTask -TaskName "Acalanto - Backup do banco" | Get-ScheduledTaskInfo
Get-ChildItem C:\acalanto\backups
```

**Para restaurar um backup**, use o script — ele faz a sequência inteira e
confere o resultado:

```powershell
powershell -ExecutionPolicy Bypass -File C:\acalanto\deploy\windows\restaurar_banco.ps1
```

> **Por que não é só "descompactar e copiar por cima":** em `banco_dados`
> existem também `acalanto_print.db-wal` e `.db-shm`. O backup é um banco
> *sozinho*, sem WAL. Se você trocar só o `.db`, o `-wal` do banco anterior
> continua na pasta e o SQLite tenta aplicá-lo sobre um arquivo que não é o
> dele — o resultado vai de "voltaram dados velhos" a banco corrompido, no
> exato momento em que a escola já está parada por causa de um problema.
> **Os três arquivos saem juntos.** É isso que o script garante.

**Atualizar o sistema depois:**

```powershell
# 1. no PC de desenvolvimento, com o "npm run build" já rodado
robocopy . \\192.168.0.50\c$\acalanto /E /XD .git .venv node_modules __pycache__ logs temp_impressao backups /XF .env agente.env *.log *.db *.db-wal *.db-shm
```

```powershell
# 2. na VM: rodar o instalador de novo reinstala as dependências e
#    reconfigura as tarefas, sem tocar no .env nem no banco
cd C:\acalanto
powershell -ExecutionPolicy Bypass -File deploy\windows\instalar.ps1 -Porta 8080

# 3. reiniciar, ESPERANDO a tarefa parar de fato antes de subir de novo
Stop-ScheduledTask -TaskName "Acalanto - Servidor de Impressao"
while ((Get-ScheduledTask -TaskName "Acalanto - Servidor de Impressao").State -ne "Ready") {
    Start-Sleep -Milliseconds 500
}
Start-ScheduledTask -TaskName "Acalanto - Servidor de Impressao"
Start-Sleep 5
Invoke-RestMethod http://localhost:8080/api/horario
```

Três detalhes que essa receita resolve e a versão ingênua não:

- **Rodar o instalador** reinstala as dependências. Sem isso, uma versão que
  acrescente uma biblioteca sobe e morre no import — sem log, porque o erro
  acontece antes de o log abrir.
- **Esperar o `Ready`** importa: `Stop-ScheduledTask` não é síncrono, e a
  tarefa está com `-MultipleInstances IgnoreNew`. Um `Start` emitido cedo
  demais é simplesmente ignorado — você sai achando que atualizou e o
  sistema fica parado.
- **O `Invoke-RestMethod` no fim** é a única parte que prova que subiu.

As exclusões do robocopy são as mesmas do passo 3 — `.env` e `*.db` fora —
para a atualização não levar embora as chaves nem o banco da VM.

---

## Se algo der errado

| Sintoma | Onde olhar |
|---|---|
| A tarefa roda e morre, **e não existe `servidor.log`** | A aplicação quebrou no *import*, antes de abrir o log — quase sempre dependência faltando. Rode o instalador de novo: o teste de fumaça mostra o erro real |
| A tarefa não inicia | `Get-ScheduledTaskInfo` mostra o último resultado; se o log existir, o erro está nele |
| "Python não encontrado" | Instale marcando *Add to PATH*, ou rode o instalador de novo |
| Tela abre, login não responde | Build do front antigo (anterior a esta migração), que chama a porta 8080 fixa. Rode `npm run build` e recopie |
| Responde em `localhost`, mas não de fora | Firewall ou perfil de rede. `Get-NetConnectionProfile` mostra o perfil; `Get-NetFirewallRule -DisplayName "Sistema de Impressao*"` mostra a regra |
| `\\192.168.0.50\c$` nega acesso | VM fora de domínio filtra o login administrativo remoto. Contorno rápido: compartilhe uma pasta comum na VM, ou copie por pendrive |
| Porta 80 ocupada | `netstat -ano \| findstr ":80 "` — normalmente é o IIS |
| Backup rodando na hora errada | Fuso da VM diferente do nosso. O horário de impressão **não** é afetado (o código fixa `America/Sao_Paulo`), mas a tarefa das 02:30 segue o relógio da máquina |
| Agente diz "Não autorizado" | `AGENTE_API_KEY` diferente entre o `.env` da VM e o `agente.env` |
| "impressora fora do ar" | O agente não alcança a VM: `CLOUD_URL`, Firewall, e se o agente está rodando |
| A VM desliga sozinha de hora em hora | A licença de avaliação expirou — veja [A licença de avaliação](#a-licença-de-avaliação) |

### Windows Defender

Vale excluir a pasta do projeto do exame em tempo real. O banco tem 190 MB e
é reescrito o dia inteiro em modo WAL; o backup diário gera outros 172 MB de
uma vez. Sem a exclusão, o antivírus relê esses arquivos a cada escrita.

```powershell
Add-MpPreference -ExclusionPath "C:\acalanto\banco_dados"
Add-MpPreference -ExclusionPath "C:\acalanto\backups"
```

Não exclua a pasta inteira do projeto: os PDFs que chegam dos professores
são justamente o que você quer que continue sendo examinado.

### Voltar atrás

Pare a tarefa na VM
(`Stop-ScheduledTask -TaskName "Acalanto - Servidor de Impressao"`), reponha
o `CLOUD_URL` antigo no `agente.env` (ou remova, que volta para `localhost`)
e rode `py app.py` no PC de antes.

Dois cuidados: **a `AGENTE_API_KEY` também tem que voltar à antiga** nos dois
lados, senão o agente volta mas não imprime; e os pedidos criados enquanto a
VM esteve no ar ficam no banco de lá.
