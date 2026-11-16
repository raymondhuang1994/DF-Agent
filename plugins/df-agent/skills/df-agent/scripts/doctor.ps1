[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string[]]$Roots,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$PythonPath,
    [string]$HostEvidencePath,
    [string]$BindingsPath,
    [string]$EnvironmentPath,
    [string]$SessionId = 'unspecified'
)
$ErrorActionPreference = 'Stop'
$DoctorScript = Join-Path $PSScriptRoot 'doctor.py'
if (-not $PythonPath) {
    $PythonCommand = Get-Command python -CommandType Application -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch '[\\/]WindowsApps[\\/]' -and (Test-Path -LiteralPath $_.Source -PathType Leaf) } |
        Select-Object -First 1
    if ($PythonCommand) {
        $PythonPath = $PythonCommand.Source
    } else {
        throw 'Supply -PythonPath with an existing Python 3.11+ interpreter. Nothing was installed.'
    }
}
$DoctorArguments = @('-X', 'utf8', '-B', $DoctorScript, 'scan', '--roots') + $Roots + @('--output', $OutputPath, '--python', $PythonPath, '--session-id', $SessionId)
if ($HostEvidencePath) { $DoctorArguments += @('--host-evidence', $HostEvidencePath) }
if ($BindingsPath) { $DoctorArguments += @('--bindings', $BindingsPath) }
if ($EnvironmentPath) { $DoctorArguments += @('--environment', $EnvironmentPath) }
& $PythonPath @DoctorArguments
if ($LASTEXITCODE -ne 0) { throw "Capability detector failed (exit $LASTEXITCODE). Dependency failures inside a valid report are reported separately." }
