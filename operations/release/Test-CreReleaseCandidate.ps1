[CmdletBinding()]
param(
    [string]$CandidateRoot = (Join-Path $PSScriptRoot "..\.."),

    [string[]]$CredentialEnvironmentFiles = @(
        "C:\10137_WorkSpace\env\.env.personal.txt",
        "C:\10137_WorkSpace\env\.env"
    ),

    [int64]$MaximumTextFileBytes = 10485760
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-GitLines {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string[]]$GitArgs
    )

    $result = @(& git -C $Repository @GitArgs)
    if ($LASTEXITCODE -ne 0) {
        throw "git failed in ${Repository}: git $($GitArgs -join ' ')"
    }
    return $result
}

function Test-ForbiddenReleasePath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $path = $RelativePath.Replace("\", "/")
    if ($path -match "(?i)(^|/)[.]git(/|$)") { return $true }
    if ($path -match "(?i)(^|/)[.]vercel(/|$)") { return $true }
    if ($path -match "(?i)(^|/)(node_modules|[.]next(?:-[^/]+)?)(/|$)") { return $true }
    if ($path -match "(?i)(^|/)(data|backups?|raw|artifacts?|reports?|logs)(/|$)") { return $true }
    if ($path -match "(?i)(^|/)[.]env($|[.])" -and $path -notmatch "(?i)(^|/)[.]env[.]example$") { return $true }
    if ($path -match "(?i)[.](db|sqlite|sqlite3|pem|key|p12|pfx)$") { return $true }
    if ($path -match "(?i)[.](db|sqlite|sqlite3)-(wal|shm)$") { return $true }
    if ($path -match "(?i)(^|/)(a?c+ess[- _]?code|credential|secret)([^/]*)(/|$)") { return $true }
    return $false
}

function Read-EnvironmentMap {
    param([Parameter(Mandatory = $true)][string[]]$Paths)

    $map = @{}
    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        foreach ($line in Get-Content -LiteralPath $path) {
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
    }
    return $map
}

$candidateResolved = (Resolve-Path -LiteralPath $CandidateRoot).Path
$candidateRootFull = [string](Invoke-GitLines -Repository $candidateResolved -GitArgs @("rev-parse", "--show-toplevel") | Select-Object -First 1)
$candidateRootFull = [IO.Path]::GetFullPath($candidateRootFull)

$candidateFiles = @()
$candidateFiles += Invoke-GitLines -Repository $candidateRootFull -GitArgs @("-c", "core.quotepath=false", "ls-files")
$candidateFiles += Invoke-GitLines -Repository $candidateRootFull -GitArgs @("-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard")
$candidateFiles = @($candidateFiles | ForEach-Object { $_.Trim().Replace("\", "/") } | Where-Object { $_ } | Sort-Object -Unique)

$forbiddenPaths = @($candidateFiles | Where-Object { Test-ForbiddenReleasePath -RelativePath $_ })

$environment = Read-EnvironmentMap -Paths $CredentialEnvironmentFiles
$credentialValues = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($entry in $environment.GetEnumerator()) {
    if ($entry.Key -notmatch "(?i)(TOKEN|SECRET|PASSWORD|PASS|KEY|DSN|DATABASE_URL|SUPABASE_URL|TURSO_DATABASE_URL|VERCEL_TOKEN)") { continue }
    $value = [string]$entry.Value
    if ($value.Length -ge 8) { [void]$credentialValues.Add($value) }
}

$binaryExtensions = @(
    ".woff", ".woff2", ".ttf", ".otf", ".ico", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".pdf", ".zip", ".gz", ".tgz", ".7z", ".exe", ".dll", ".bin"
)
$secretMatchPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$conflictMarkerPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$skippedLargeCount = 0

foreach ($relativePath in $candidateFiles) {
    $fullPath = [IO.Path]::GetFullPath((Join-Path $candidateRootFull $relativePath))
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) { continue }
    $file = Get-Item -LiteralPath $fullPath
    if ($file.Length -gt $MaximumTextFileBytes) {
        $skippedLargeCount++
        continue
    }
    if ($binaryExtensions -contains $file.Extension.ToLowerInvariant()) { continue }

    try { $content = [IO.File]::ReadAllText($fullPath) } catch { continue }
    if ($content -match "(?m)^(<<<<<<<|=======|>>>>>>>)") {
        [void]$conflictMarkerPaths.Add($relativePath)
    }
    foreach ($value in $credentialValues) {
        if ($content.IndexOf($value, [StringComparison]::Ordinal) -ge 0) {
            [void]$secretMatchPaths.Add($relativePath)
            break
        }
    }
}

$diffCheck = @(& git -C $candidateRootFull diff --check)
$diffCheckPassed = ($LASTEXITCODE -eq 0)

$result = [pscustomobject]@{
    CandidateRoot = $candidateRootFull
    CandidateFileCount = $candidateFiles.Count
    CredentialValueCount = $credentialValues.Count
    SecretMatchCount = $secretMatchPaths.Count
    SecretMatchPaths = @($secretMatchPaths | Sort-Object)
    ForbiddenPathCount = $forbiddenPaths.Count
    ForbiddenPaths = $forbiddenPaths
    ConflictMarkerCount = $conflictMarkerPaths.Count
    ConflictMarkerPaths = @($conflictMarkerPaths | Sort-Object)
    SkippedLargeFileCount = $skippedLargeCount
    DiffCheck = if ($diffCheckPassed) { "passed" } else { "failed" }
}
$result | ConvertTo-Json -Depth 4

if ($secretMatchPaths.Count -gt 0 -or $forbiddenPaths.Count -gt 0 -or $conflictMarkerPaths.Count -gt 0 -or -not $diffCheckPassed) {
    throw "Release candidate safety checks failed. Only counts and matched paths were emitted; credential values were never printed."
}
