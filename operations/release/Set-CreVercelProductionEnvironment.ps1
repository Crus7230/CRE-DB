[CmdletBinding()]
param(
    [string]$PersonalEnvironmentFile = "C:\10137_WorkSpace\env\.env.personal.txt",

    [string]$GlobalEnvironmentFile = "C:\10137_WorkSpace\env\.env",

    [string]$EnvironmentMutationManifest = (Join-Path $PSScriptRoot "vercel-env-mutations.tsv"),

    [string]$ProjectId = "prj_1DTajzRAaw2IbqffiAwN2aZWC5Bb",

    [string]$TeamId = "team_ZraFevjGRitnuj6w5suDl9Cs",

    [string]$ScopeSlug = "grus-projects-dc1b5fb9",

    [string]$ExpectedProjectName = "cre-db",

    [string]$ExpectedRootDirectory = "web",

    [string]$ExpectedGitOrganization = "Crus7230",

    [string]$ExpectedGitRepository = "CRE-DB",

    [string]$ExpectedProductionBranch = "main",

    [string]$ExpectedSupabaseProjectRef = "rjalzmmiqhrdmhojbxsk",

    [string]$VercelCliVersion = "59.13.1",

    [Parameter(Mandatory = $true)]
    [switch]$RootQaApproved,

    [Parameter(Mandatory = $true)]
    [switch]$ApproveEnvironmentMutation,

    [Parameter(Mandatory = $true)]
    [switch]$GitHubIntegratedWorkflow,

    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RootQaApproved -or -not $ApproveEnvironmentMutation -or -not $GitHubIntegratedWorkflow) {
    throw "Root QA, environment mutation, and GitHub-integrated workflow gates are all required."
}

function Get-EnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Environment authority file not found: $Path"
    }

    $values = @(
        Get-Content -LiteralPath $Path |
            ForEach-Object {
                if ($_ -notmatch "^\s*(?:export\s+)?$([Regex]::Escape($Key))\s*=\s*(.*)$") { return }
                $value = $matches[1].Trim()
                if ($value.Length -ge 2) {
                    $first = $value[0]
                    $last = $value[$value.Length - 1]
                    if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                        $value = $value.Substring(1, $value.Length - 2)
                    }
                }
                if (-not [string]::IsNullOrWhiteSpace($value)) { $value }
            }
    )
    $distinct = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($value in $values) { [void]$distinct.Add([string]$value) }
    if ($distinct.Count -eq 0) {
        throw "Required key $Key is absent from its declared authority file."
    }
    if ($distinct.Count -ne 1) {
        throw "Required key $Key has conflicting definitions in its declared authority file."
    }
    return [string](@($distinct)[0])
}

function Invoke-VercelApi {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [ValidateSet("GET", "POST")][string]$Method = "GET",
        [AllowNull()][object]$Body
    )

    $npx = (Get-Command npx.cmd -ErrorAction Stop).Source
    $arguments = @(
        "--yes",
        "vercel@$VercelCliVersion",
        "api",
        $Endpoint,
        "--scope",
        $ScopeSlug,
        "--raw",
        "--non-interactive"
    )
    if ($Method -ne "GET") {
        $arguments += @("--method", $Method)
    }

    if ($null -ne $Body) {
        $arguments += @("--input", "-")
        $inputJson = $Body | ConvertTo-Json -Depth 8 -Compress
        $lines = @($inputJson | & $npx @arguments 2>$null)
    } else {
        $lines = @(& $npx @arguments 2>$null)
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticated Vercel API request failed: $Method $Endpoint"
    }

    $raw = $lines -join [Environment]::NewLine
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    try {
        return $raw | ConvertFrom-Json
    } catch {
        throw "Vercel API returned a non-JSON response for: $Method $Endpoint"
    }
}

function Test-ProductionEnvironment {
    param([Parameter(Mandatory = $true)][object]$EnvironmentVariable)

    $gitBranchProperty = $EnvironmentVariable.PSObject.Properties["gitBranch"]
    $gitBranch = if ($null -eq $gitBranchProperty) { $null } else { [string]$gitBranchProperty.Value }
    return (
        "production" -in @($EnvironmentVariable.target) -and
        [string]::IsNullOrWhiteSpace($gitBranch)
    )
}

function Get-EnvironmentIdentity {
    param([Parameter(Mandatory = $true)][object]$EnvironmentVariable)

    $targets = @($EnvironmentVariable.target | Sort-Object) -join ","
    $gitBranchProperty = $EnvironmentVariable.PSObject.Properties["gitBranch"]
    $gitBranch = if ($null -eq $gitBranchProperty) { "" } else { [string]$gitBranchProperty.Value }
    return "$($EnvironmentVariable.id)|$($EnvironmentVariable.key)|$($EnvironmentVariable.type)|$targets|$gitBranch"
}

$expectedKeys = @(
    "SUPABASE_URL",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_PROJECT_REF",
    "DASHBOARD_DATA_PROVIDER",
    "VWORLD_KEY",
    "DATA_GO_KR_KEY",
    "DART_API_KEY",
    "KRX_API_KEY"
)

$manifestEntries = @(
    Get-Content -LiteralPath $EnvironmentMutationManifest |
        Where-Object { $_ -and -not $_.StartsWith("#") } |
        ForEach-Object {
            $fields = @($_ -split "`t")
            if ($fields.Count -ne 3) { throw "Invalid environment mutation manifest row." }
            [pscustomobject]@{ Key = $fields[0]; Source = $fields[1]; Requirement = $fields[2] }
        }
)
$manifestKeys = @($manifestEntries | ForEach-Object Key)
$manifestDifference = @(Compare-Object -ReferenceObject $expectedKeys -DifferenceObject $manifestKeys)
if ($manifestEntries.Count -ne 8 -or $manifestDifference.Count -gt 0) {
    throw "Environment mutation manifest must contain exactly the reviewed eight keys."
}

$mutationValues = @{}
foreach ($entry in $manifestEntries) {
    switch ($entry.Source) {
        "personal" { $mutationValues[$entry.Key] = Get-EnvironmentValue -Path $PersonalEnvironmentFile -Key $entry.Key }
        "global" { $mutationValues[$entry.Key] = Get-EnvironmentValue -Path $GlobalEnvironmentFile -Key $entry.Key }
        "constant" {
            if ($entry.Key -ne "DASHBOARD_DATA_PROVIDER") { throw "Unknown constant environment key." }
            $mutationValues[$entry.Key] = "supabase"
        }
        default { throw "Unknown environment authority source for $($entry.Key)." }
    }
}

if (-not [string]::Equals([string]$mutationValues["SUPABASE_PROJECT_REF"], $ExpectedSupabaseProjectRef, [StringComparison]::Ordinal)) {
    throw "Supabase project ref does not match the reviewed release target."
}
try { $supabaseUri = [Uri]([string]$mutationValues["SUPABASE_URL"]) } catch { throw "SUPABASE_URL is not a valid URI." }
if ($supabaseUri.Scheme -ne "https" -or $supabaseUri.Host -ne "$ExpectedSupabaseProjectRef.supabase.co") {
    throw "SUPABASE_URL does not match the reviewed release project ref."
}

$user = Invoke-VercelApi -Endpoint "/v2/user"
$project = Invoke-VercelApi -Endpoint "/v9/projects/$ProjectId"
if (
    $project.id -ne $ProjectId -or
    $project.name -ne $ExpectedProjectName -or
    $project.accountId -ne $TeamId -or
    $project.rootDirectory -ne $ExpectedRootDirectory -or
    $project.link.type -ne "github" -or
    $project.link.org -ne $ExpectedGitOrganization -or
    $project.link.repo -ne $ExpectedGitRepository -or
    $project.link.productionBranch -ne $ExpectedProductionBranch
) {
    throw "Vercel project/team/root/Git integration mismatch."
}

$beforeResponse = Invoke-VercelApi -Endpoint "/v9/projects/$ProjectId/env"
$beforeEnvironments = @($beforeResponse.envs)
$schemaEntries = @(
    $beforeEnvironments |
        Where-Object { $_.key -eq "DASHBOARD_SUPABASE_RPC_SCHEMA" -and (Test-ProductionEnvironment $_) }
)
if ($schemaEntries.Count -gt 1) {
    throw "Multiple unscoped production DASHBOARD_SUPABASE_RPC_SCHEMA entries exist."
}
if ($schemaEntries.Count -eq 1) {
    $schema = Invoke-VercelApi -Endpoint "/v9/projects/$ProjectId/env/$($schemaEntries[0].id)"
    if ([string]$schema.value -ne "public") {
        throw "Existing production DASHBOARD_SUPABASE_RPC_SCHEMA is not public."
    }
    $schema = $null
}

$beforeUnrelatedIdentities = @(
    $beforeEnvironments |
        Where-Object { $_.key -notin $expectedKeys } |
        ForEach-Object { Get-EnvironmentIdentity $_ } |
        Sort-Object
)
$beforeTargetKeys = @(
    $beforeEnvironments |
        Where-Object { $_.key -in $expectedKeys -and (Test-ProductionEnvironment $_) } |
        ForEach-Object Key |
        Sort-Object -Unique
)

if ($ValidateOnly) {
    [pscustomobject]@{
        Mode = "validate-only"
        CliAccount = [string]$user.user.username
        ProjectId = [string]$project.id
        ProjectName = [string]$project.name
        RootDirectory = [string]$project.rootDirectory
        GitRepository = "$($project.link.org)/$($project.link.repo)"
        ProductionBranch = [string]$project.link.productionBranch
        ReviewedMutationKeys = $expectedKeys
        ExistingReviewedProductionKeys = $beforeTargetKeys
        ExistingEnvironmentCount = $beforeEnvironments.Count
        UnrelatedEnvironmentCount = $beforeUnrelatedIdentities.Count
        RpcSchemaPreflight = if ($schemaEntries.Count -eq 0) { "absent" } else { "public" }
        DeploymentTriggered = $false
    } | ConvertTo-Json -Depth 4
    exit 0
}

foreach ($entry in $manifestEntries) {
    $body = [ordered]@{
        key = $entry.Key
        value = [string]$mutationValues[$entry.Key]
        type = "encrypted"
        target = @("production")
    }
    [void](Invoke-VercelApi -Endpoint "/v10/projects/$ProjectId/env?upsert=true" -Method POST -Body $body)
}

$afterResponse = Invoke-VercelApi -Endpoint "/v9/projects/$ProjectId/env"
$afterEnvironments = @($afterResponse.envs)
$afterUnrelatedIdentities = @(
    $afterEnvironments |
        Where-Object { $_.key -notin $expectedKeys } |
        ForEach-Object { Get-EnvironmentIdentity $_ } |
        Sort-Object
)
if (@(Compare-Object -ReferenceObject $beforeUnrelatedIdentities -DifferenceObject $afterUnrelatedIdentities).Count -gt 0) {
    throw "Unrelated Vercel environment metadata changed."
}

$verifiedKeys = [Collections.Generic.List[string]]::new()
foreach ($key in $expectedKeys) {
    $entries = @(
        $afterEnvironments |
            Where-Object { $_.key -eq $key -and (Test-ProductionEnvironment $_) }
    )
    if ($entries.Count -ne 1) {
        throw "Expected exactly one unscoped production entry for $key after mutation."
    }
    $readback = Invoke-VercelApi -Endpoint "/v9/projects/$ProjectId/env/$($entries[0].id)"
    if (-not [string]::Equals([string]$readback.value, [string]$mutationValues[$key], [StringComparison]::Ordinal)) {
        throw "Value readback mismatch for $key."
    }
    $verifiedKeys.Add($key)
    $readback = $null
}

[pscustomobject]@{
    Mode = "environment-only"
    CliAccount = [string]$user.user.username
    ProjectId = [string]$project.id
    ProjectName = [string]$project.name
    RootDirectory = [string]$project.rootDirectory
    GitRepository = "$($project.link.org)/$($project.link.repo)"
    ProductionBranch = [string]$project.link.productionBranch
    ReviewedMutationKeys = $expectedKeys
    ExactValueReadbackKeys = @($verifiedKeys)
    ExactValueReadbackCount = $verifiedKeys.Count
    BeforeEnvironmentCount = $beforeEnvironments.Count
    AfterEnvironmentCount = $afterEnvironments.Count
    UnrelatedEnvironmentIdentitiesPreserved = $afterUnrelatedIdentities.Count
    RpcSchemaPreflight = if ($schemaEntries.Count -eq 0) { "absent" } else { "public" }
    DeploymentTriggered = $false
} | ConvertTo-Json -Depth 4
