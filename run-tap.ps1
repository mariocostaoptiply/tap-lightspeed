# run-tap.ps1
# Script para instalar dependências, gerar catalog e executar o tap

param(
    [switch]$SkipInstall,      # Pular poetry install
    [switch]$SkipCatalog,      # Pular geração do catalog
    [string]$ConfigFile = ".\config.json",
    [string]$CatalogFile = "catalog.json",
    [string]$StateFile = $null  # Opcional: arquivo de state para replicação incremental
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  TAP-R-LIGHTSPEED Runner Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Poetry Install
if (-not $SkipInstall) {
    Write-Host "[1/4] Instalando dependências com Poetry..." -ForegroundColor Yellow
    poetry install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRO: poetry install falhou!" -ForegroundColor Red
        exit 1
    }
    Write-Host "     Dependências instaladas com sucesso!" -ForegroundColor Green
} else {
    Write-Host "[1/4] Pulando poetry install (--SkipInstall)" -ForegroundColor Gray
}

Write-Host ""

# 2. Ativar venv
Write-Host "[2/4] Ativando ambiente virtual..." -ForegroundColor Yellow
$venvPath = ".\venv\Scripts\Activate.ps1"
if (Test-Path $venvPath) {
    . $venvPath
    Write-Host "     Venv ativado!" -ForegroundColor Green
} else {
    Write-Host "AVISO: venv não encontrado em $venvPath, continuando..." -ForegroundColor DarkYellow
}

Write-Host ""

# 3. Gerar Catalog (com correção de encoding)
if (-not $SkipCatalog) {
    Write-Host "[3/4] Gerando catalog..." -ForegroundColor Yellow
    
    # Gerar catalog com Out-File (vai ter BOM)
    $tempCatalog = "$CatalogFile.tmp"
    tap-r-lightspeed --config $ConfigFile --discover | Out-File -FilePath $tempCatalog -Encoding utf8
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRO: Falha ao gerar catalog!" -ForegroundColor Red
        Remove-Item -Path $tempCatalog -ErrorAction SilentlyContinue
        exit 1
    }
    
    # Converter para UTF-8 sem BOM
    Write-Host "     Convertendo para UTF-8 sem BOM..." -ForegroundColor Yellow
    $content = Get-Content $tempCatalog -Raw
    [System.IO.File]::WriteAllText($CatalogFile, $content, [System.Text.UTF8Encoding]::new($false))
    Remove-Item -Path $tempCatalog -ErrorAction SilentlyContinue
    
    # Verificar encoding
    $bytes = [byte[]](Get-Content $CatalogFile -Encoding Byte -TotalCount 4)
    if ($bytes[0] -eq 123) {
        Write-Host "     Catalog gerado com sucesso! (UTF-8 sem BOM)" -ForegroundColor Green
    } else {
        Write-Host "AVISO: Encoding pode estar incorreto. Primeiros bytes: $($bytes -join ' ')" -ForegroundColor DarkYellow
    }
} else {
    Write-Host "[3/4] Pulando geração do catalog (--SkipCatalog)" -ForegroundColor Gray
}

Write-Host ""

# 4. Executar TAP
Write-Host "[4/4] Executando tap-r-lightspeed..." -ForegroundColor Yellow
Write-Host "     Config: $ConfigFile" -ForegroundColor Gray
Write-Host "     Catalog: $CatalogFile" -ForegroundColor Gray

$tapArgs = @("--config", $ConfigFile, "--catalog", $CatalogFile)

if ($StateFile -and (Test-Path $StateFile)) {
    Write-Host "     State: $StateFile" -ForegroundColor Gray
    $tapArgs += @("--state", $StateFile)
}

Write-Host ""
Write-Host "----------------------------------------" -ForegroundColor DarkGray
Write-Host "Iniciando extração de dados..." -ForegroundColor Cyan
Write-Host "----------------------------------------" -ForegroundColor DarkGray
Write-Host ""

# Executar tap com target-jsonl
tap-r-lightspeed @tapArgs | target-jsonl

$exitCode = $LASTEXITCODE

Write-Host ""
Write-Host "----------------------------------------" -ForegroundColor DarkGray

if ($exitCode -eq 0) {
    Write-Host "Extração concluída com sucesso!" -ForegroundColor Green
} else {
    Write-Host "Extração falhou com código: $exitCode" -ForegroundColor Red
}

exit $exitCode




