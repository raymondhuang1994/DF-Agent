[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Plan', 'Apply', 'Status')][string]$Action,
    [string]$StateDir,
    [string[]]$Roots,
    [string]$PythonPath,
    [string]$OutputPath,
    [string]$PlanPath,
    [string]$BindingsPath,
    [string]$SessionId = 'unspecified'
)
$ErrorActionPreference = 'Stop'
function Assert-NoReparsePoint([string]$LiteralPath) {
    $CandidatePath = [System.IO.Path]::GetFullPath($LiteralPath)
    while ($CandidatePath) {
        if (Test-Path -LiteralPath $CandidatePath) {
            $CandidateItem = Get-Item -LiteralPath $CandidatePath -Force
            if ($CandidateItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw 'TeamAdvisor setup paths must not traverse links or reparse points.'
            }
        }
        $CandidatePath = [System.IO.Path]::GetDirectoryName($CandidatePath)
    }
}
if (-not $StateDir) {
    if (-not $env:LOCALAPPDATA) { throw 'Supply -StateDir; LOCALAPPDATA is unavailable.' }
    $StateDir = Join-Path $env:LOCALAPPDATA 'TeamAdvisor'
}
$SetupScript = Join-Path $PSScriptRoot 'setup.py'
$ConfigPath = Join-Path $StateDir 'setup.local.json'
Assert-NoReparsePoint $ConfigPath
if (-not $PythonPath -and (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    # Read only the dedicated TeamAdvisor setting, never other app profiles.
    $SavedSetup = Get-Content -LiteralPath $ConfigPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($SavedSetup.schema_version -ne 'team-advisor-setup/1') { throw 'Unsupported saved setup schema.' }
    $PythonPath = [string]$SavedSetup.python
}
if (-not $PythonPath) {
    $PythonCommand = Get-Command python -CommandType Application -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch '[\\/]WindowsApps[\\/]' -and (Test-Path -LiteralPath $_.Source -PathType Leaf) } |
        Select-Object -First 1
    if ($PythonCommand) { $PythonPath = $PythonCommand.Source }
}
if (-not $PythonPath -or $PythonPath -match '[\\/]WindowsApps[\\/]' -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Supply -PythonPath with a real Python 3.11+ interpreter. Nothing was installed.'
}
Assert-NoReparsePoint $PythonPath
$SetupArguments = @('-X', 'utf8', '-B', $SetupScript, $Action.ToLowerInvariant(), '--state-dir', $StateDir)
switch ($Action) {
    'Plan' {
        if (-not $Roots -or -not $OutputPath) { throw 'Plan requires -Roots and -OutputPath.' }
        $SetupArguments += @('--roots') + $Roots + @('--python', $PythonPath, '--output', $OutputPath, '--session-id', $SessionId)
        if ($BindingsPath) { $SetupArguments += @('--bindings', $BindingsPath) }
    }
    'Apply' {
        if (-not $PlanPath) { throw 'Apply requires -PlanPath.' }
        $SetupArguments += @('--plan', $PlanPath)
    }
    'Status' {
        $SetupArguments += @('--session-id', $SessionId)
        if ($OutputPath) { $SetupArguments += @('--output', $OutputPath) }
    }
}
& $PythonPath @SetupArguments
if ($LASTEXITCODE -ne 0) { throw "TeamAdvisor setup failed (exit $LASTEXITCODE)." }
