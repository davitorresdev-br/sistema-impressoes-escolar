# Restauração do banco a partir de um backup .gz, na VM Windows.
#
#   powershell -ExecutionPolicy Bypass -File deploy\windows\restaurar_banco.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\windows\restaurar_banco.ps1 -Backup C:\acalanto\backups\acalanto_print_2026-09-20_0230.db.gz
#
# Por que existe um script para isto, em vez de "descompacte e copie por cima":
# o banco em modo WAL sao TRES arquivos (.db, .db-wal, .db-shm). O backup e um
# banco sozinho, sem WAL. Trocando so o .db, o -wal do banco anterior fica na
# pasta e o SQLite tenta aplica-lo sobre um arquivo que nao e o dele — de
# "voltaram dados velhos" a banco corrompido. Os tres saem juntos, sempre.
#
# Nada e apagado: o banco atual e RENOMEADO para .quebrado-<carimbo>.

param(
    # Backup a restaurar. Sem isto, usa o .gz mais recente da pasta backups.
    [string]$Backup = "",
    # Pula a confirmação (para uso em automação).
    [switch]$Forcar
)

$ErrorActionPreference = "Stop"

$admin = ([Security.Principal.WindowsPrincipal] `
          [Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Error "Rode este script em um PowerShell aberto COMO ADMINISTRADOR (ele para a tarefa do servidor)."
    exit 1
}

$RAIZ = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$TAREFA = "Acalanto - Servidor de Impressao"
$pastaBanco = Join-Path $RAIZ "banco_dados"
$bancoAtivo = Join-Path $pastaBanco "acalanto_print.db"
$venvPython = Join-Path $RAIZ ".venv\Scripts\python.exe"

# --------------------------------------------------------------- qual backup
if (-not $Backup) {
    $pastaBackups = Join-Path $RAIZ "backups"
    if (-not (Test-Path $pastaBackups)) {
        Write-Error "Pasta de backups nao encontrada em $pastaBackups. Passe o arquivo com -Backup."
        exit 1
    }
    $maisNovo = Get-ChildItem -Path $pastaBackups -Filter "acalanto_print_*.db.gz" |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $maisNovo) {
        Write-Error "Nenhum backup .db.gz encontrado em $pastaBackups."
        exit 1
    }
    $Backup = $maisNovo.FullName
}
if (-not (Test-Path $Backup)) {
    Write-Error "Backup nao encontrado: $Backup"
    exit 1
}

$info = Get-Item $Backup
Write-Host "==> Backup escolhido:"
Write-Host "      $($info.FullName)"
Write-Host "      $([math]::Round($info.Length / 1MB, 1)) MB, de $($info.LastWriteTime)"
Write-Host ""

if (-not $Forcar) {
    Write-Host "Isto vai PARAR o servidor e substituir o banco atual." -ForegroundColor Yellow
    Write-Host "O banco atual sera renomeado (nao apagado)." -ForegroundColor Yellow
    $resposta = Read-Host "Digite RESTAURAR para continuar"
    if ($resposta -ne "RESTAURAR") {
        Write-Host "Cancelado. Nada foi alterado."
        exit 0
    }
}

# --------------------------------------------------------------- parar
Write-Host "==> Parando a tarefa do servidor"
$tarefa = Get-ScheduledTask -TaskName $TAREFA -ErrorAction SilentlyContinue
if ($tarefa) {
    Stop-ScheduledTask -TaskName $TAREFA
    # Stop-ScheduledTask nao e sincrono: sem esperar, o processo antigo ainda
    # pode estar com o banco aberto quando tentarmos renomear.
    $limite = 30
    while ((Get-ScheduledTask -TaskName $TAREFA).State -ne "Ready" -and $limite -gt 0) {
        Start-Sleep -Seconds 1
        $limite--
    }
    if ((Get-ScheduledTask -TaskName $TAREFA).State -ne "Ready") {
        Write-Error "A tarefa nao parou em 30s. Verifique no Agendador de Tarefas antes de continuar."
        exit 1
    }
    Write-Host "    parada."
} else {
    Write-Host "    tarefa nao registrada nesta maquina — seguindo."
}

# --------------------------------------------------------------- tirar os tres
$carimbo = Get-Date -Format "yyyy-MM-dd_HHmm"
$movidos = 0
foreach ($sufixo in @("", "-wal", "-shm")) {
    $alvo = "$bancoAtivo$sufixo"
    if (Test-Path $alvo) {
        $destino = "$alvo.quebrado-$carimbo"
        Move-Item -Path $alvo -Destination $destino -Force
        Write-Host "    guardado: $(Split-Path $destino -Leaf)"
        $movidos++
    }
}
if ($movidos -eq 0) { Write-Host "    (nao havia banco no lugar)" }

# --------------------------------------------------------------- descompactar
Write-Host "==> Descompactando o backup"
$entrada = [System.IO.File]::OpenRead($Backup)
$saida = [System.IO.File]::Create($bancoAtivo)
try {
    $gzip = New-Object System.IO.Compression.GzipStream($entrada, [System.IO.Compression.CompressionMode]::Decompress)
    try { $gzip.CopyTo($saida) } finally { $gzip.Dispose() }
} finally {
    $saida.Dispose()
    $entrada.Dispose()
}
Write-Host "    $([math]::Round((Get-Item $bancoAtivo).Length / 1MB, 1)) MB restaurados"

# --------------------------------------------------------------- conferir
Write-Host "==> Conferindo o banco restaurado"
if (Test-Path $venvPython) {
    & $venvPython (Join-Path $RAIZ "deploy\conferir_banco.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Error "A conferencia falhou. O banco anterior continua salvo como *.quebrado-$carimbo."
        exit 1
    }
} else {
    Write-Host "    (.venv nao encontrado — pulei a conferencia)"
}

# --------------------------------------------------------------- subir
if ($tarefa) {
    Write-Host "==> Subindo o servidor"
    Start-ScheduledTask -TaskName $TAREFA
    Start-Sleep -Seconds 5
}

Write-Host ""
Write-Host "======================================================================"
Write-Host "Restauracao concluida."
Write-Host ""
Write-Host "  O banco anterior ficou guardado em:"
Write-Host "    $pastaBanco\acalanto_print.db.quebrado-$carimbo (e -wal/-shm)"
Write-Host "  Apague so depois de confirmar que o sistema voltou."
Write-Host ""
Write-Host "  CONFIRA AGORA:"
Write-Host "    1. Invoke-RestMethod http://localhost:8080/api/horario"
Write-Host "    2. Entrar no sistema de outra maquina e ver a fila"
Write-Host "    3. Avisar que pedidos entre o backup e agora se perderam"
Write-Host "======================================================================"
