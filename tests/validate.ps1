param(
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [string]$Matlab = (Get-Command matlab -ErrorAction Stop).Source,
    [string]$Python = (Get-Command python -ErrorAction Stop).Source,
    [switch]$IncludeCrash
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$destination = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $destination) {
    throw "Choose a new test output directory. Already exists: $destination"
}
New-Item -ItemType Directory -Path $destination | Out-Null
$target = $destination.Replace('\','/').Replace("'","''")
$previousScenario = $env:ACCFM_TEST_SCENARIO

Push-Location $root
try {
    & $Python core/build_observed.py --check
    if ($LASTEXITCODE -ne 0) { throw 'Observer generation check failed.' }

    $tests = "addpath('tests'); regression(fullfile('$target','regression')); " +
        "extended(fullfile('$target','extended')); protections; " +
        "recovery(fullfile('$target','recovery')); case_inputs(fullfile('$target','cases'));"
    & $Matlab -wait -sd $root -logfile (Join-Path $destination 'matlab-validation.log') -batch $tests
    if ($LASTEXITCODE -ne 0) { throw 'MATLAB validation failed.' }

    $folders = @(Get-ChildItem -LiteralPath $destination -Directory -Recurse -Filter 'scenario_*' |
        ForEach-Object FullName)
    & $Python python/read_run.py --require-plan @folders
    if ($LASTEXITCODE -ne 0) { throw 'Scenario validation failed.' }

    $env:ACCFM_TEST_SCENARIO = Join-Path $destination 'regression/traced/scenario_000003'
    & $Python -m unittest discover -s tests -p 'test_*.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Python unit tests failed.' }

    if ($IncludeCrash) {
        & $Python tests/crash_resume.py (Join-Path $destination 'crash') --matlab $Matlab
        if ($LASTEXITCODE -ne 0) { throw 'Crash and writer lock validation failed.' }
    }
    Write-Output "ACCFMLAB_VALIDATION_PASSED $destination"
}
finally {
    $env:ACCFM_TEST_SCENARIO = $previousScenario
    Pop-Location
}
