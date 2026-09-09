[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DeploymentUrl,

    [string]$CandidateRoot = (Join-Path $PSScriptRoot "..\.."),

    [string]$EnvironmentFile = "C:\10137_WorkSpace\env\.env.personal.txt",

    [string]$ProjectId = "prj_1DTajzRAaw2IbqffiAwN2aZWC5Bb",

    [string]$TeamId = "team_ZraFevjGRitnuj6w5suDl9Cs",

    [string]$ProductionDomain = "cre-db.vercel.app",

    [string]$VercelCliVersion = "59.13.1",

    [Parameter(Mandatory = $true)]
    [switch]$RootStagedQaApproved,

    [Parameter(Mandatory = $true)]
    [switch]$ApproveProductionPromotion
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RootStagedQaApproved -or -not $ApproveProductionPromotion) {
    throw "Both -RootStagedQaApproved and -ApproveProductionPromotion are required. This script changes the production alias."
}

function Read-EnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Environment file not found: $Path" }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -notmatch "^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$") { continue }
        if ($matches[1] -ne $Name) { continue }
        $value = $matches[2].Trim()
        if ($value.Length -ge 2) {
            $first = $value[0]
            $last = $value[$value.Length - 1]
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($value)) { return $value }
    }
    throw "$Name is absent from the approved environment file."
}

function Invoke-VercelCli {
    param(
        [Parameter(Mandatory = $true)][string[]]$CliArgs,
        [Parameter(Mandatory = $true)][string]$SensitiveValue
    )

    $npx = (Get-Command npx.cmd -ErrorAction Stop).Source
    $output = @(& $npx --yes "vercel@$VercelCliVersion" @CliArgs 2>&1)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $safe = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
        $safe = $safe.Replace($SensitiveValue, "[redacted]", [StringComparison]::Ordinal)
        throw "Vercel CLI failed (exit $exitCode): $safe"
    }
    return @($output | ForEach-Object { [string]$_ })
}

$candidateResolved = (Resolve-Path -LiteralPath $CandidateRoot).Path
$candidateGitRoot = [string](& git -C $candidateResolved rev-parse --show-toplevel)
if ($LASTEXITCODE -ne 0) { throw "Candidate is not a Git checkout: $CandidateRoot" }
$candidateGitRoot = [IO.Path]::GetFullPath($candidateGitRoot)

$candidateStatus = @(& git -C $candidateGitRoot status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0) { throw "Unable to inspect candidate Git status." }
if ($candidateStatus.Count -gt 0) { throw "Candidate must remain committed and clean through promotion." }

$deploymentUriValue = [Uri]$DeploymentUrl
if ($deploymentUriValue.Scheme -ne "https" -or $deploymentUriValue.Host -notmatch "[.]vercel[.]app$") {
    throw "DeploymentUrl must be an HTTPS Vercel deployment URL."
}

$vercelToken = Read-EnvironmentValue -Path $EnvironmentFile -Name "VERCEL_TOKEN"
$headers = @{ Authorization = "Bearer $vercelToken" }
$deploymentApiUri = "https://api.vercel.com/v13/deployments/$($deploymentUriValue.Host)?teamId=$TeamId"
$targetDeployment = Invoke-RestMethod -Method Get -Uri $deploymentApiUri -Headers $headers
if ($targetDeployment.projectId -ne $ProjectId -or $targetDeployment.readyState -ne "READY" -or $targetDeployment.target -ne "production") {
    throw "Target deployment is not a READY staged production deployment for the expected project."
}
if (@($targetDeployment.alias) -contains $ProductionDomain) {
    throw "Target deployment already owns the production alias; refusing a redundant promotion."
}

$deploymentsUri = "https://api.vercel.com/v6/deployments?projectId=$ProjectId&teamId=$TeamId&target=production&state=READY&limit=20"
$deploymentList = Invoke-RestMethod -Method Get -Uri $deploymentsUri -Headers $headers
$previousProduction = @(
    @($deploymentList.deployments) |
        Where-Object { @($_.alias) -contains $ProductionDomain } |
        Sort-Object created -Descending |
        Select-Object -First 1
)
if ($previousProduction.Count -ne 1) {
    throw "Unable to identify exactly one currently aliased production deployment for rollback."
}

$oldVercelToken = $env:VERCEL_TOKEN
$oldVercelOrgId = $env:VERCEL_ORG_ID
$oldVercelProjectId = $env:VERCEL_PROJECT_ID
$oldNpmCache = $env:npm_config_cache
try {
    $env:VERCEL_TOKEN = $vercelToken
    $env:VERCEL_ORG_ID = $TeamId
    $env:VERCEL_PROJECT_ID = $ProjectId
    $env:npm_config_cache = Join-Path (Split-Path -Parent $candidateGitRoot) "npm-cache-vercel-release"

    [void](Invoke-VercelCli -CliArgs @("promote", $DeploymentUrl, "--yes", "--cwd", $candidateGitRoot, "--no-color") -SensitiveValue $vercelToken)

    $deadline = [DateTimeOffset]::UtcNow.AddMinutes(3)
    $promoted = $null
    do {
        $promoted = Invoke-RestMethod -Method Get -Uri $deploymentApiUri -Headers $headers
        if (@($promoted.alias) -contains $ProductionDomain) { break }
        Start-Sleep -Seconds 3
    } while ([DateTimeOffset]::UtcNow -lt $deadline)

    if (@($promoted.alias) -notcontains $ProductionDomain) {
        throw "Promotion command succeeded but production-alias readback did not converge within three minutes."
    }

    [pscustomobject]@{
        ProjectId = $ProjectId
        ProductionDomain = $ProductionDomain
        PreviousDeploymentId = $previousProduction[0].uid
        PreviousDeploymentUrl = $previousProduction[0].url
        PromotedDeploymentId = $promoted.id
        PromotedDeploymentUrl = $DeploymentUrl
        ReadyState = $promoted.readyState
        AliasVerified = $true
        NextGate = "Repeat the complete anonymous/authenticated/API/header/timing/mobile production QA checklist."
    } | ConvertTo-Json -Depth 4
}
finally {
    $env:VERCEL_TOKEN = $oldVercelToken
    $env:VERCEL_ORG_ID = $oldVercelOrgId
    $env:VERCEL_PROJECT_ID = $oldVercelProjectId
    $env:npm_config_cache = $oldNpmCache
    $vercelToken = $null
}
