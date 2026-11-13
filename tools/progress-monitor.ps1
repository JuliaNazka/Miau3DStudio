# Miau 3D Studio - monitor de progresso da instalacao
# Mede cada etapa a cada poucos segundos e grava D:\Miau3DStudio\logs\progress.json
param([int]$IntervalSeconds = 5)

$Root = 'D:\Miau3DStudio'
$Out = Join-Path $Root 'logs\progress.json'
$GB = 1GB

# Tamanhos exatos dos modelos (API do Hugging Face, 13/11/2026)
$ModelsTotal = 9862024333 + 14009810812 + 4313519161 + 814890934 + 9862024337
# Estimativas calibradas para as etapas sem total conhecido
$VsExpected = 5.5 * $GB      # VS Build Tools (VCTools + recomendados)
$PyDownload = 4.5 * $GB      # cache do uv (torch cu126 + dependencias)
$PyInstalled = 5.5 * $GB     # ambiente Python instalado

$SitePkgs = Join-Path $Root 'envs\miau\Lib\site-packages'
$NvccPath = 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin\nvcc.exe'
$RasterDir = Join-Path $Root 'vendor\Hunyuan3D-2\hy3dgen\texgen\custom_rasterizer'

function Get-DirBytes([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    $sum = 0
    try {
        foreach ($f in [System.IO.Directory]::EnumerateFiles($Path, '*', 'AllDirectories')) {
            try { $sum += ([System.IO.FileInfo]$f).Length } catch {}
        }
    } catch {}
    return $sum
}

function Fmt([double]$bytes) { '{0:N1}' -f ($bytes / $GB) }

function Stage($id, $label, $weight, $percent, $status, $detail) {
    [ordered]@{
        id = $id; label = $label; weight = $weight
        percent = [math]::Round([math]::Max(0, [math]::Min(100, $percent)), 1)
        status = $status; detail = $detail
    }
}

while ($true) {
    $stages = @()

    # 1. Compilador C++ (VS Build Tools)
    $vsBytes = Get-DirBytes (Join-Path $Root 'tools\BuildTools')
    $vsRunning = @(Get-Process -Name vs_installer, vs_setup_bootstrapper -ErrorAction SilentlyContinue).Count -gt 0
    $cl = Get-ChildItem (Join-Path $Root 'tools\BuildTools\VC\Tools\MSVC\*\bin\Hostx64\x64\cl.exe') -ErrorAction SilentlyContinue | Select-Object -First 1
    $vsw = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $vsComplete = $false
    if (Test-Path $vsw) { $vsComplete = (& $vsw -all -products * -path (Join-Path $Root 'tools\BuildTools') -property isComplete 2>$null) -eq '1' }
    if ($cl -and ($vsComplete -or -not $vsRunning)) {
        $stages += Stage 'vs' 'Compilador C++ (VS Build Tools)' 20 100 'done' ("{0} GB instalados" -f (Fmt $vsBytes))
    } elseif ($vsBytes -gt 0 -or $vsRunning) {
        $stages += Stage 'vs' 'Compilador C++ (VS Build Tools)' 20 ([math]::Min(95, 100 * $vsBytes / $VsExpected)) 'running' ("{0} de ~{1} GB (estimado)" -f (Fmt $vsBytes), (Fmt $VsExpected))
    } else {
        $stages += Stage 'vs' 'Compilador C++ (VS Build Tools)' 20 0 'waiting' 'aguardando'
    }

    # 2. Python + PyTorch
    $torchOk = (Test-Path (Join-Path $SitePkgs 'torch\lib\torch_cuda.dll')) -and (Test-Path (Join-Path $SitePkgs 'gradio')) -and (Test-Path (Join-Path $SitePkgs 'trimesh'))
    $uvBytes = Get-DirBytes (Join-Path $Root 'cache\uv')
    $envBytes = Get-DirBytes (Join-Path $Root 'envs\miau')
    if ($torchOk) {
        $stages += Stage 'py' 'Python + PyTorch (CUDA)' 20 100 'done' ("ambiente com {0} GB" -f (Fmt $envBytes))
    } elseif ($envBytes -gt 0.2 * $GB) {
        $p = 80 + 20 * $envBytes / $PyInstalled
        $stages += Stage 'py' 'Python + PyTorch (CUDA)' 20 ([math]::Min(98, $p)) 'running' ("instalando: {0} de ~{1} GB" -f (Fmt $envBytes), (Fmt $PyInstalled))
    } elseif ($uvBytes -gt 0) {
        $stages += Stage 'py' 'Python + PyTorch (CUDA)' 20 ([math]::Min(80, 80 * $uvBytes / $PyDownload)) 'running' ("baixando: {0} de ~{1} GB" -f (Fmt $uvBytes), (Fmt $PyDownload))
    } else {
        $stages += Stage 'py' 'Python + PyTorch (CUDA)' 20 0 'waiting' 'aguardando'
    }

    # 3. Modelos Hunyuan3D (total exato)
    $mBytes = Get-DirBytes (Join-Path $Root 'models\tencent')
    $incomplete = @(Get-ChildItem (Join-Path $Root 'models\tencent') -Recurse -Force -Filter '*.incomplete' -ErrorAction SilentlyContinue).Count
    $mPct = 100 * $mBytes / $ModelsTotal
    if ($mPct -ge 99.9 -and $incomplete -eq 0) {
        $stages += Stage 'models' 'Modelos de IA Hunyuan3D' 40 100 'done' ("{0} GB baixados" -f (Fmt $ModelsTotal))
    } elseif ($mBytes -gt 0) {
        $stages += Stage 'models' 'Modelos de IA Hunyuan3D' 40 ([math]::Min(99.9, $mPct)) 'running' ("{0} de {1} GB" -f (Fmt $mBytes), (Fmt $ModelsTotal))
    } else {
        $stages += Stage 'models' 'Modelos de IA Hunyuan3D' 40 0 'waiting' 'aguardando'
    }

    # 4. CUDA Toolkit 12.6
    $cudaRunning = @(Get-Process -Name 'cuda_12.6.3_windows_network' -ErrorAction SilentlyContinue).Count -gt 0
    if (Test-Path $NvccPath) {
        $stages += Stage 'cuda' 'CUDA Toolkit 12.6' 10 100 'done' 'nvcc instalado'
    } elseif ($cudaRunning) {
        $stages += Stage 'cuda' 'CUDA Toolkit 12.6' 10 50 'running' 'instalando'
    } else {
        $stages += Stage 'cuda' 'CUDA Toolkit 12.6' 10 0 'waiting' 'aguardando o compilador'
    }

    # 5. Compilar a extensao de textura
    $built = @(Get-ChildItem $SitePkgs -Filter 'custom_rasterizer*' -ErrorAction SilentlyContinue).Count -gt 0
    if ($built) {
        $stages += Stage 'build' 'Compilar extensao de textura' 10 100 'done' 'custom_rasterizer pronto'
    } elseif (Test-Path (Join-Path $RasterDir 'build')) {
        $stages += Stage 'build' 'Compilar extensao de textura' 10 50 'running' 'compilando'
    } else {
        $stages += Stage 'build' 'Compilar extensao de textura' 10 0 'waiting' 'aguardando CUDA'
    }

    $wsum = ($stages | ForEach-Object { $_.weight } | Measure-Object -Sum).Sum
    $overall = ($stages | ForEach-Object { $_.percent * $_.weight } | Measure-Object -Sum).Sum / $wsum
    $doc = [ordered]@{
        title = 'Instalacao do Miau 3D Studio'
        updatedAt = (Get-Date).ToString('o')
        overall = [math]::Round($overall, 1)
        cFreeGB = [math]::Round((Get-PSDrive C).Free / $GB, 1)
        stages = $stages
    }
    $json = $doc | ConvertTo-Json -Depth 5
    $tmp = "$Out.tmp"
    [System.IO.File]::WriteAllText($tmp, $json, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -Force $tmp $Out

    if ($overall -ge 100) { break }
    Start-Sleep -Seconds $IntervalSeconds
}
