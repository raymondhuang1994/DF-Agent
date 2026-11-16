[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string[]]$Roots,
    [string]$OutputPath,
    [string]$PythonPath,
    [string]$HostEvidencePath,
    [string]$BindingsPath,
    [string]$EnvironmentPath,
    [string]$SessionId = 'unspecified',
    [string]$TaskId,
    [string[]]$WriteRoot,
    [ValidateSet('setup', 'memory', 'feedback', 'output', 'runtime')][string[]]$AllowOperation,
    [string[]]$DocumentRoot
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
$DoctorArguments = @('-X', 'utf8', '-B', $DoctorScript)
if ($TaskId) { $DoctorArguments += @('--task-id', $TaskId) }
foreach ($PathValue in $WriteRoot) { $DoctorArguments += @('--write-root', $PathValue) }
foreach ($OperationValue in $AllowOperation) { $DoctorArguments += @('--allow-operation', $OperationValue) }
foreach ($PathValue in $DocumentRoot) { $DoctorArguments += @('--document-root', $PathValue) }
$DoctorArguments += @('scan', '--roots') + $Roots + @('--python', $PythonPath, '--session-id', $SessionId)
if ($OutputPath) { $DoctorArguments += @('--output', $OutputPath) }
if ($HostEvidencePath) { $DoctorArguments += @('--host-evidence', $HostEvidencePath) }
if ($BindingsPath) { $DoctorArguments += @('--bindings', $BindingsPath) }
if ($EnvironmentPath) { $DoctorArguments += @('--environment', $EnvironmentPath) }
& $PythonPath @DoctorArguments
if ($LASTEXITCODE -ne 0) { throw "Capability detector failed (exit $LASTEXITCODE). Dependency failures inside a valid report are reported separately." }
