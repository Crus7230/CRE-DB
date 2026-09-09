[CmdletBinding()]
param(
    [string]$CandidateRoot = (Join-Path $PSScriptRoot "..\.."),

    [string]$PersonalEnvironmentFile = "C:\10137_WorkSpace\env\.env.personal.txt",

    [string]$GlobalEnvironmentFile = "C:\10137_WorkSpace\env\.env",

    [string]$EnvironmentMutationManifest = (Join-Path $PSScriptRoot "vercel-env-mutations.tsv"),

    [string]$ProjectId = "prj_1DTajzRAaw2IbqffiAwN2aZWC5Bb",

    [string]$TeamId = "team_ZraFevjGRitnuj6w5suDl9Cs",

    [string]$ExpectedProjectName = "cre-db",

    [string]$ExpectedRootDirectory = "web",

    [string]$VercelCliVersion = "59.13.1",

    [Parameter(Mandatory = $true)]
    [switch]$RootQaApproved,

    [Parameter(Mandatory = $true)]
    [switch]$ApproveEnvironmentMutation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RootQaApproved -or -not $ApproveEnvironmentMutation) {
    throw "Both -RootQaApproved and -ApproveEnvironmentMutation are required. This script mutates production environment metadata."
}

function Read-EnvironmentMap {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Environment file not found: $Path"
    }
    $map = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -notmatch "^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$") { continue }
        $name = $matches[1]
        $value = $matches[2].Trim()
        if ($value.Length -ge 2) {
            $first = $value[0]
            $last = $value[$value.Length - 1]
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($value)) { $map[$name] = $value }
    }
    return $map
}

function Protect-Output {
    param(
        [Parameter(Mandatory = $true)][string[]]$Lines,
        [Parameter(Mandatory = $true)][string[]]$SensitiveValues
    )

    $safe = $Lines -join [Environment]::NewLine
    foreach ($value in $SensitiveValues) {
        if ([string]::IsNullOrWhiteSpace($value)) { continue }
        $safe = $safe.Replace($value, "[redacted]", [StringComparison]::Ordinal)
    }
    return $safe
}

function Invoke-VercelCli {
    param(
        [Parameter(Mandatory = $true)][string[]]$CliArgs,
        [AllowNull()][string]$StandardInputValue,
        [Parameter(Mandatory = $true)][string[]]$SensitiveValues
    )

    $npx = (Get-Command npx.cmd -ErrorAction Stop).Source
    if ($null -eq $StandardInputValue) {
        $output = @(& $npx --yes "vercel@$VercelCliVersion" @CliArgs 2>&1)
    } else {
        $output = @($StandardInputValue | & $npx --yes "vercel@$VercelCliVersion" @CliArgs 2>&1)
    }
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $safeOutput = Protect-Output -Lines @($output | ForEach-Object { [string]$_ }) -SensitiveValues $SensitiveValues
        throw "Vercel CLI failed (exit $exitCode): $safeOutput"
    }
    return @($output | ForEach-Object { [string]$_ })
}

function Get-EnvironmentIdentity {
    param([Parameter(Mandatory = $true)]$EnvironmentVariable)

    $targets = @($EnvironmentVariable.target) | ForEach-Object { [string]$_ } | Sort-Object
    return "$($EnvironmentVariable.id)|$($EnvironmentVariable.key)|$($targets -join ',')|$($EnvironmentVariable.gitBranch)"
}

$candidateResolved = (Resolve-Path -LiteralPath $CandidateRoot).Path
$candidateGitRoot = [string](& git -C $candidateResolved rev-parse --show-toplevel)
if ($LASTEXITCODE -ne 0) { throw "Candidate is not a Git checkout: $CandidateRoot" }
$candidateGitRoot = [IO.Path]::GetFullPath($candidateGitRoot)

$candidateStatus = @(& git -C $candidateGitRoot status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0) { throw "Unable to inspect candidate Git status." }
if ($candidateStatus.Count -gt 0) {
    throw "Candidate must be committed and clean before staged production deployment."
}

& (Join-Path $PSScriptRoot "Test-CreReleaseCandidate.ps1") -CandidateRoot $candidateGitRoot -CredentialEnvironmentFiles @($PersonalEnvironmentFile, $GlobalEnvironmentFile)
if ($LASTEXITCODE -ne 0) { throw "Release candidate safety check failed." }

$personalEnvironment = Read-EnvironmentMap -Path $PersonalEnvironmentFile
$globalEnvironment = Read-EnvironmentMap -Path $GlobalEnvironmentFile
if (-not $personalEnvironment.ContainsKey("VERCEL_TOKEN")) {
    throw "VERCEL_TOKEN is absent from the approved environment file."
}
$vercelToken = [string]$personalEnvironment["VERCEL_TOKEN"]

$mutationEntries = @(
    Get-Content -LiteralPath $EnvironmentMutationManifest |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith("#") } |
        ForEach-Object {
            $fields = @($_ -split "`t", 3)
            if ($fields.Count -ne 3) { throw "Environment mutation row must be '<key><TAB><source><TAB><requirement>': $_" }
            [pscustomobject]@{
                Key = $fields[0].Trim()
                Source = $fields[1].Trim().ToLowerInvariant()
                Requirement = $fields[2].Trim()
            }
        }
)
if ($mutationEntries.Count -eq 0) { throw "Environment mutation manifest is empty." }
$mutationKeys = @($mutationEntries | ForEach-Object Key)
$duplicateKeys = @($mutationKeys | Group-Object | Where-Object Count -gt 1 | ForEach-Object Name)
if ($duplicateKeys.Count -gt 0) { throw "Environment mutation manifest has duplicate keys: $($duplicateKeys -join ', ')" }
$allowedKeys = @(
    "SUPABASE_URL", "SUPABASE_SECRET_KEY", "DASHBOARD_DATA_PROVIDER",
    "VWORLD_KEY", "DATA_GO_KR_KEY", "DART_API_KEY", "KRX_API_KEY"
)
$unexpectedKeys = @($mutationKeys | Where-Object { $_ -notin $allowedKeys })
if ($unexpectedKeys.Count -gt 0) { throw "Unexpected key is not allowed in the mutation manifest: $($unexpectedKeys -join ', ')" }

$mutationValues = @{}
foreach ($entry in $mutationEntries) {
    if ($entry.Source -eq "constant") {
        if ($entry.Key -ne "DASHBOARD_DATA_PROVIDER") { throw "Only DASHBOARD_DATA_PROVIDER may use constant authority." }
        $mutationValues[$entry.Key] = "supabase"
        continue
    }
    $authority = if ($entry.Source -eq "personal") {
        $personalEnvironment
    } elseif ($entry.Source -eq "global") {
        $globalEnvironment
    } else {
        throw "Unknown environment authority '$($entry.Source)' for $($entry.Key)."
    }
    if (-not $authority.ContainsKey($entry.Key)) {
        throw "Required environment key is absent from its approved $($entry.Source) authority: $($entry.Key)"
    }
    $mutationValues[$entry.Key] = [string]$authority[$entry.Key]
}

$sensitiveValues = @($vercelToken) + @($mutationKeys | ForEach-Object { [string]$mutationValues[$_] })
$headers = @{ Authorization = "Bearer $vercelToken" }
$projectUri = "https://api.vercel.com/v9/projects/$ProjectId`?teamId=$TeamId"
$environmentUri = "https://api.vercel.com/v9/projects/$ProjectId/env?teamId=$TeamId"

$project = Invoke-RestMethod -Method Get -Uri $projectUri -Headers $headers
if ($project.id -ne $ProjectId -or $project.name -ne $ExpectedProjectName -or $project.rootDirectory -ne $ExpectedRootDirectory) {
    throw "Vercel project identity/root mismatch. Refusing to mutate or deploy."
}

$beforeResponse = Invoke-RestMethod -Method Get -Uri $environmentUri -Headers $headers
$beforeEnvironments = @($beforeResponse.envs)
$beforeUnrelatedIdentities = @(
    $beforeEnvironments |
        Where-Object { $_.key -notin $mutationKeys } |
        ForEach-Object { Get-EnvironmentIdentity -EnvironmentVariable $_ } |
        Sort-Object
)

$existingTargetKeys = @()
foreach ($key in $mutationKeys) {
    $matching = @(
        $beforeEnvironments |
            Where-Object { $_.key -eq $key -and (@($_.target) -contains "production") -and [string]::IsNullOrWhiteSpace([string]$_.gitBranch) }
    )
    if ($matching.Count -gt 1) { throw "Multiple unscoped production entries exist for $key; resolve manually." }
    if ($matching.Count -eq 1) { $existingTargetKeys += $key }
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

    foreach ($key in $mutationKeys) {
        $value = [string]$mutationValues[$key]
        if ($key -in $existingTargetKeys) {
            [void](Invoke-VercelCli -CliArgs @("env", "update", $key, "production", "--yes", "--cwd", $candidateGitRoot, "--no-color") -StandardInputValue $value -SensitiveValues $sensitiveValues)
        } else {
            $addArguments = @("env", "add", $key, "production", "--yes", "--cwd", $candidateGitRoot, "--no-color")
            if ($key -match "(SECRET|KEY|TOKEN)$") { $addArguments += "--sensitive" }
            [void](Invoke-VercelCli -CliArgs $addArguments -StandardInputValue $value -SensitiveValues $sensitiveValues)
        }
    }

    $afterResponse = Invoke-RestMethod -Method Get -Uri $environmentUri -Headers $headers
    $afterEnvironments = @($afterResponse.envs)
    foreach ($identity in $beforeUnrelatedIdentities) {
        $afterIdentities = @($afterEnvironments | ForEach-Object { Get-EnvironmentIdentity -EnvironmentVariable $_ })
        if ($identity -notin $afterIdentities) {
            throw "A pre-existing Vercel environment entry changed identity or disappeared; stop before deployment."
        }
    }
    foreach ($key in $mutationKeys) {
        $matching = @($afterEnvironments | Where-Object { $_.key -eq $key -and (@($_.target) -contains "production") })
        if ($matching.Count -eq 0) { throw "Environment readback did not find production key: $key" }
    }

    $commit = [string](& git -C $candidateGitRoot rev-parse HEAD)
    if ($LASTEXITCODE -ne 0) { throw "Unable to read release commit." }
    $deployOutput = Invoke-VercelCli -CliArgs @(
        "deploy", "--prod", "--skip-domain", "--yes", "--cwd", $candidateGitRoot, "--no-color",
        "--meta", "releaseCommit=$commit"
    ) -StandardInputValue $null -SensitiveValues $sensitiveValues

    $deploymentUrl = [string](
        $deployOutput |
            Select-String -Pattern "https://[a-zA-Z0-9.-]+[.]vercel[.]app" -AllMatches |
            ForEach-Object { $_.Matches.Value } |
            Select-Object -Last 1
    )
    if ([string]::IsNullOrWhiteSpace($deploymentUrl)) {
        throw "Vercel returned success but no deployment URL was found."
    }

    [void](Invoke-VercelCli -CliArgs @("inspect", $deploymentUrl, "--wait", "--timeout=10m", "--cwd", $candidateGitRoot, "--no-color") -StandardInputValue $null -SensitiveValues $sensitiveValues)
    $deploymentHost = ([Uri]$deploymentUrl).Host
    $deploymentUri = "https://api.vercel.com/v13/deployments/$deploymentHost`?teamId=$TeamId"
    $deployment = Invoke-RestMethod -Method Get -Uri $deploymentUri -Headers $headers
    if ($deployment.projectId -ne $ProjectId -or $deployment.readyState -ne "READY") {
        throw "Staged deployment readback did not confirm the expected project in READY state."
    }

    [pscustomobject]@{
        ProjectId = $ProjectId
        ProjectName = $ExpectedProjectName
        RootDirectory = $ExpectedRootDirectory
        ReleaseCommit = $commit
        EnvironmentKeysChanged = $mutationKeys
        EnvironmentAuthorities = @($mutationEntries | Select-Object Key, Source, Requirement)
        PreExistingEnvironmentEntryCount = $beforeEnvironments.Count
        PostUpdateEnvironmentEntryCount = $afterEnvironments.Count
        DeploymentId = $deployment.id
        DeploymentUrl = $deploymentUrl
        ReadyState = $deployment.readyState
        ProductionAliasChanged = $false
        NextGate = "Run authenticated/anonymous staged QA, then explicitly promote."
    } | ConvertTo-Json -Depth 4
}
finally {
    $env:VERCEL_TOKEN = $oldVercelToken
    $env:VERCEL_ORG_ID = $oldVercelOrgId
    $env:VERCEL_PROJECT_ID = $oldVercelProjectId
    $env:npm_config_cache = $oldNpmCache
    $vercelToken = $null
    $personalEnvironment = $null
    $globalEnvironment = $null
    $mutationValues = $null
    $sensitiveValues = $null
}
