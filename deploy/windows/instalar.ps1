# Instalação do SERVIDOR do Sistema de Impressão numa VM Windows.
#
#   Abra o PowerShell COMO ADMINISTRADOR, na pasta do projeto:
#     powershell -ExecutionPolicy Bypass -File deploy\windows\instalar.ps1
#
# Pode rodar de novo quantas vezes quiser: nada é sobrescrito à toa, e o
# .env existente NUNCA é tocado (é onde moram as chaves).
#
# O que este script NÃO faz, de propósito:
#   * copiar o banco de dados     -> ver docs/MIGRACAO-VM-WINDOWS.md
#   * gerar/rotacionar as chaves  -> idem, é decisão com impacto
#   * configurar o agente         -> idem
# São passos que mexem em dados reais e merecem alguém olhando.

param(
    # Porta em que o sistema vai atender. 8080 é o padrão (mesmo de hoje);
    # 80 deixa o endereço sem porta (http://impressao.exemplo.com.br).
    [int]$Porta = 8080,
    # Horário do backup diário.
    [string]$HoraBackup = "02:30",
    # Não registrar as tarefas agendadas (só preparar o ambiente).
    [switch]$SemTarefas
)

$ErrorActionPreference = "Stop"

# $ErrorActionPreference NAO alcanca programas externos: se o pip falhar (sem
# internet, proxy da escola, PyPI bloqueado), o erro rola a tela e o script
# SEGUE — registrando as tarefas e anunciando "instalacao concluida" sobre um
# ambiente quebrado. O servidor so morreria la na frente, no import, sem
# deixar log. Toda chamada a programa externo passa por aqui.
function Executar {
    param([Parameter(Mandatory)][string]$Programa,
          [string[]]$Argumentos = @(),
          [string]$Etapa = "")
    & $Programa @Argumentos
    if ($LASTEXITCODE -ne 0) {
        $oque = if ($Etapa) { $Etapa } else { "$Programa $($Argumentos -join ' ')" }
        Write-Error "FALHOU: $oque (codigo $LASTEXITCODE). Nenhuma tarefa foi registrada."
        exit 1
    }
}

# --------------------------------------------------------------- conferências
$admin = ([Security.Principal.WindowsPrincipal] `
          [Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Error "Rode este script em um PowerShell aberto COMO ADMINISTRADOR."
    exit 1
}

$RAIZ = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Write-Host "==> Projeto em: $RAIZ"
Write-Host "==> Porta: $Porta"
Write-Host ""

# --------------------------------------------------------------- Python
Write-Host "==> Procurando o Python"
$python = $null
foreach ($candidato in @("py", "python")) {
    try {
        $versao = & $candidato -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $versao) { $python = $candidato; break }
    } catch { }
}
if (-not $python) {
    Write-Error "Python não encontrado. Instale do python.org (marque 'Add to PATH') e rode de novo."
    exit 1
}
Write-Host "    $python -> versão $versao"

# zoneinfo (usado no fuso America/Sao_Paulo) existe a partir do 3.9.
$partes = $versao.Split(".")
if ([int]$partes[0] -lt 3 -or ([int]$partes[0] -eq 3 -and [int]$partes[1] -lt 9)) {
    Write-Error "Python $versao é antigo demais — o projeto usa zoneinfo (3.9+)."
    exit 1
}

# --------------------------------------------------------------- ambiente virtual
$venvPython = Join-Path $RAIZ ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "==> Criando o ambiente virtual (.venv)"
    Executar $python @("-m", "venv", (Join-Path $RAIZ ".venv")) "criacao do ambiente virtual"
} else {
    Write-Host "==> Ambiente virtual já existe"
}
if (-not (Test-Path $venvPython)) {
    Write-Error "O ambiente virtual nao apareceu em $venvPython."
    exit 1
}

# Esta etapa exige que a VM alcance a internet (PyPI).
Write-Host "==> Instalando as dependências"
Executar $venvPython @("-m", "pip", "install", "--quiet", "--upgrade", "pip") "atualizacao do pip"
Executar $venvPython @("-m", "pip", "install", "--quiet", "-r", (Join-Path $RAIZ "requirements.txt")) "instalacao das dependencias (a VM precisa de saida para a internet)"

# Teste de fumaca: importa tudo o que o servidor precisa no arranque e resolve
# o fuso. E aqui que um requirements incompleto tem de aparecer.
#
# O caso classico e o tzdata: o Windows nao tem base de fusos propria
# (zoneinfo.TZPATH vem vazio), e o app.py resolve America/Sao_Paulo no IMPORT,
# antes de abrir o log. Sem este teste, a falha viraria uma tarefa agendada
# morrendo calada e um logs\servidor.log que nunca chega a existir.
Write-Host "==> Teste de fumaça (dependências + fuso)"
$prova = "from zoneinfo import ZoneInfo; from datetime import datetime; from google.oauth2 import id_token; import flask, flask_cors, dotenv, pypdf, itsdangerous, werkzeug, waitress; print('    Sao Paulo agora:', datetime.now(ZoneInfo('America/Sao_Paulo')).isoformat(timespec='seconds'))"
Executar $venvPython @("-c", $prova) "teste de fumaca (dependencias + fuso America/Sao_Paulo)"

# --------------------------------------------------------------- pastas
foreach ($pasta in @("logs", "banco_dados", "backups")) {
    $caminho = Join-Path $RAIZ $pasta
    if (-not (Test-Path $caminho)) { New-Item -ItemType Directory -Path $caminho | Out-Null }
}

# --------------------------------------------------------------- .env
$envArquivo = Join-Path $RAIZ ".env"
if (-not (Test-Path $envArquivo)) {
    Write-Host "==> Criando .env a partir do exemplo (PRECISA ser preenchido)"
    Copy-Item (Join-Path $RAIZ ".env.example") $envArquivo
    $extra = @"

# --- acrescentado pelo instalador da VM Windows ---
# Atende a rede inteira (os professores acessam pelo IP/nome da VM).
ACALANTO_HOST=0.0.0.0
ACALANTO_PORT=$Porta
# NAO ligue ACALANTO_ATRAS_DE_PROXY sem um proxy reverso na frente:
# qualquer cliente poderia forjar o proprio IP e escapar do limite de
# tentativas de login.
ACALANTO_LOG=$($RAIZ -replace '\\','/')/logs/servidor.log
"@
    Add-Content -Path $envArquivo -Value $extra -Encoding UTF8
    Write-Host "    !! Preencha ACALANTO_SECRET_KEY e AGENTE_API_KEY em $envArquivo"
} else {
    Write-Host "==> .env já existe — preservado (as chaves não são tocadas)"

    # A PORTA e a unica coisa que o instalador ajusta num .env existente.
    # Sem isto, rodar de novo com -Porta diferente abriria a regra de firewall
    # nova e deixaria o sistema atendendo na porta ANTIGA, anunciando sucesso.
    $utf8SemBom = New-Object System.Text.UTF8Encoding $false
    $linhas = [System.IO.File]::ReadAllLines($envArquivo, [System.Text.Encoding]::UTF8)
    $achou = $false
    $mudou = $false
    for ($i = 0; $i -lt $linhas.Count; $i++) {
        if ($linhas[$i] -match '^\s*ACALANTO_PORT\s*=\s*(.*)$') {
            $achou = $true
            $atual = $Matches[1].Trim()
            if ($atual -ne "$Porta") {
                $linhas[$i] = "ACALANTO_PORT=$Porta"
                $mudou = $true
                Write-Host "    ACALANTO_PORT: $atual -> $Porta" -ForegroundColor Yellow
            }
        }
    }
    if (-not $achou) {
        $linhas += "ACALANTO_PORT=$Porta"
        $mudou = $true
        Write-Host "    ACALANTO_PORT ausente — acrescentado ($Porta)" -ForegroundColor Yellow
    }
    if ($mudou) {
        [System.IO.File]::WriteAllLines($envArquivo, $linhas, $utf8SemBom)
        Write-Host ""
        Write-Host "    !! A PORTA MUDOU. Duas coisas dependem disso:" -ForegroundColor Yellow
        Write-Host "       1. reiniciar a tarefa do servidor" -ForegroundColor Yellow
        Write-Host "       2. o CLOUD_URL do agente, no PC da impressora" -ForegroundColor Yellow
        Write-Host ""
    }
}

# --------------------------------------------------------------- firewall
# A regra vale para TODOS os perfis (-Profile Any), de proposito.
#
# Limita-la a Dominio/Privado seria uma armadilha silenciosa: uma VM em grupo
# de trabalho nao passa pelo assistente de localizacao de rede e a placa cai
# como "Publica" (Rede nao identificada). A regra existiria sem valer, o
# instalador anunciaria "porta liberada", e o teste do roteiro em
# http://localhost nem perceberia — porque nao passa pelo firewall. So os
# professores e o agente descobririam, cada um do seu lugar.
Write-Host "==> Liberando a porta $Porta no Firewall (todos os perfis)"
$regra = "Sistema de Impressao - Servidor ($Porta)"
# Remove TODAS as regras anteriores do sistema, nao so a desta porta: numa
# troca de porta, a regra antiga ficaria para tras deixando aberta uma porta
# em que nao ha mais nada atendendo.
Get-NetFirewallRule -DisplayName "Sistema de Impressao - Servidor (*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $regra -Direction Inbound -Protocol TCP `
    -LocalPort $Porta -Action Allow -Profile Any | Out-Null

# Para restringir a origem, acrescente -RemoteAddress LocalSubnet a linha
# acima. NAO e o padrao aqui: se a escola tiver mais de uma faixa de rede
# (servidores numa, salas de aula em outra), isso bloquearia justamente os
# professores.

Write-Host "==> Perfil de rede desta VM:"
$perfis = @(Get-NetConnectionProfile)
foreach ($p in $perfis) {
    Write-Host "    $($p.InterfaceAlias): $($p.NetworkCategory)  (rede '$($p.Name)')"
}
$publicas = @($perfis | Where-Object { $_.NetworkCategory -eq "Public" })
if ($publicas.Count -gt 0) {
    Write-Host ""
    Write-Host "    Ha placa em perfil PUBLICO. A porta $Porta continua liberada (a" -ForegroundColor Yellow
    Write-Host "    regra vale para todos os perfis), mas 'Publico' tambem desliga" -ForegroundColor Yellow
    Write-Host "    descoberta de rede e compartilhamentos. Para mudar:" -ForegroundColor Yellow
    foreach ($p in $publicas) {
        Write-Host "      Set-NetConnectionProfile -InterfaceAlias '$($p.InterfaceAlias)' -NetworkCategory Private" -ForegroundColor Yellow
    }
    Write-Host ""
}

# --------------------------------------------------------------- tarefas
if (-not $SemTarefas) {
    # O servidor roda como TAREFA AGENDADA disparada na inicialização, com a
    # conta SYSTEM. É o equivalente prático de um serviço: sobe sozinho com a
    # máquina, SEM ninguém precisar fazer logon, e se reinicia se cair.
    # (Se um dia quiser um serviço "de verdade", com controle pelo
    # services.msc, o NSSM faz isso — mas exige baixar um executável a mais.)
    Write-Host "==> Registrando a tarefa do servidor (inicia com a máquina)"
    $acaoServidor = New-ScheduledTaskAction -Execute $venvPython `
        -Argument "app.py" -WorkingDirectory $RAIZ
    $gatilhoServidor = New-ScheduledTaskTrigger -AtStartup
    $contaSistema = New-ScheduledTaskPrincipal -UserId "SYSTEM" `
        -LogonType ServiceAccount -RunLevel Highest
    $ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName "Acalanto - Servidor de Impressao" `
        -Action $acaoServidor -Trigger $gatilhoServidor -Principal $contaSistema `
        -Settings $ajustes -Force | Out-Null

    Write-Host "==> Registrando a tarefa de backup diário ($HoraBackup)"
    $acaoBackup = New-ScheduledTaskAction -Execute $venvPython `
        -Argument "deploy\windows\backup_banco.py" -WorkingDirectory $RAIZ
    $gatilhoBackup = New-ScheduledTaskTrigger -Daily -At $HoraBackup
    $ajustesBackup = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName "Acalanto - Backup do banco" `
        -Action $acaoBackup -Trigger $gatilhoBackup -Principal $contaSistema `
        -Settings $ajustesBackup -Force | Out-Null
}

Write-Host ""
Write-Host "======================================================================"
Write-Host "Instalação concluída. FALTAM os passos que mexem em dados reais:"
Write-Host ""
Write-Host "  1. Preencher as chaves em $envArquivo"
Write-Host "       ACALANTO_SECRET_KEY e AGENTE_API_KEY"
Write-Host "       (gere com: $venvPython -c ""import secrets; print(secrets.token_hex(32))"")"
Write-Host ""
Write-Host "  2. Copiar o banco para $RAIZ\banco_dados\acalanto_print.db"
Write-Host "       e conferir com:"
Write-Host "       $venvPython $RAIZ\deploy\conferir_banco.py"
Write-Host ""
Write-Host "  3. Subir o servidor:"
Write-Host "       Start-ScheduledTask -TaskName 'Acalanto - Servidor de Impressao'"
Write-Host "       Endereço: http://<ip-desta-vm>:$Porta/"
Write-Host ""
Write-Host "  4. No PC da impressora, apontar o agente (agente.env):"
Write-Host "       CLOUD_URL=http://<ip-desta-vm>:$Porta"
Write-Host "       AGENTE_API_KEY=<a mesma chave do passo 1>"
Write-Host ""
Write-Host "Roteiro completo: docs\MIGRACAO-VM-WINDOWS.md"
Write-Host "======================================================================"
