[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 65433,

    [string]$BlendFile = "",

    [string]$BlenderPath = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
)

$resolvedBlender = (Resolve-Path -LiteralPath $BlenderPath -ErrorAction Stop).Path
$arguments = @()

if ($BlendFile) {
    $resolvedBlend = (Resolve-Path -LiteralPath $BlendFile -ErrorAction Stop).Path
    if ([System.IO.Path]::GetExtension($resolvedBlend) -ne ".blend") {
        throw "O arquivo precisa ter extensão .blend: $resolvedBlend"
    }
    $arguments += "`"$resolvedBlend`""
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($listener) {
    $owner = ($listener | Select-Object -First 1).OwningProcess
    throw "A porta $Port já está em uso pelo processo $owner."
}

$previousPort = [Environment]::GetEnvironmentVariable("ORTHOSIS_BRIDGE_PORT", "Process")
try {
    [Environment]::SetEnvironmentVariable("ORTHOSIS_BRIDGE_PORT", "$Port", "Process")
    $startParameters = @{
        FilePath = $resolvedBlender
        PassThru = $true
    }
    if ($arguments.Count -gt 0) {
        $startParameters.ArgumentList = $arguments
    }
    $process = Start-Process @startParameters
}
finally {
    [Environment]::SetEnvironmentVariable("ORTHOSIS_BRIDGE_PORT", $previousPort, "Process")
}

[PSCustomObject]@{
    ProcessId = $process.Id
    Port = $Port
    BlendFile = if ($BlendFile) { $resolvedBlend } else { "(startup vazio)" }
}
