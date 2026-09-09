[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$LegacySourceContentRoot,

    [Parameter(Mandatory = $true)]
    [string]$CanonicalSourceContentRoot,

    [string]$ManifestPath = (Join-Path $PSScriptRoot "source-delta-files.txt"),

    [string]$ExpectedBaseCommit = "eef5faf4a773f3b6080e852380ba6cfcac05c5db",

    [string]$ExpectedReleaseBranch = "codex/cre-supabase-release-20260909",

    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-GitLines {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string[]]$GitArgs
    )

    $result = @(& git -c "safe.directory=$Repository" -C $Repository @GitArgs)
    if ($LASTEXITCODE -ne 0) {
        throw "git failed in ${Repository}: git $($GitArgs -join ' ')"
    }
    return $result
}

function Resolve-RepositoryRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $root = [string](Invoke-GitLines -Repository $resolved -GitArgs @("rev-parse", "--show-toplevel") | Select-Object -First 1)
    return [IO.Path]::GetFullPath($root)
}

function Get-WorkingTreePaths {
    param([Parameter(Mandatory = $true)][string]$Repository)

    $paths = @()
    $paths += Invoke-GitLines -Repository $Repository -GitArgs @("-c", "core.quotepath=false", "diff", "--name-only", "HEAD", "--")
    $paths += Invoke-GitLines -Repository $Repository -GitArgs @("-c", "core.quotepath=false", "diff", "--cached", "--name-only", "--")
    $paths += Invoke-GitLines -Repository $Repository -GitArgs @("-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard")
    return @($paths | ForEach-Object { $_.Trim().Replace("\", "/") } | Where-Object { $_ } | Sort-Object -Unique)
}

function Test-ForbiddenReleasePath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $path = $RelativePath.Replace("\", "/")
    if ($path -match "(?i)(^|/)[.]git(/|$)") { return $true }
    if ($path -match "(?i)(^|/)[.]vercel(/|$)") { return $true }
    if ($path -match "(?i)(^|/)(node_modules|[.]next)(/|$)") { return $true }
    if ($path -match "(?i)(^|/)(data|backups?|raw|artifacts?|reports?|logs)(/|$)") { return $true }
    if ($path -match "(?i)(^|/)[.]env($|[.])" -and $path -notmatch "(?i)(^|/)[.]env[.]example$") { return $true }
    if ($path -match "(?i)[.](db|sqlite|sqlite3|pem|key|p12|pfx)$") { return $true }
    if ($path -match "(?i)[.](db|sqlite|sqlite3)-(wal|shm)$") { return $true }
    if ($path -match "(?i)(^|/)(a?c+ess[- _]?code|credential|secret)([^/]*)(/|$)") { return $true }
    return $false
}

function Resolve-ContainedPath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    if ([IO.Path]::IsPathRooted($RelativePath)) {
        throw "Manifest path must be relative: $RelativePath"
    }
    if (@($RelativePath.Replace("\", "/").Split("/") | Where-Object { $_ -eq ".." }).Count -gt 0) {
        throw "Manifest path cannot traverse upward: $RelativePath"
    }

    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $candidate = [IO.Path]::GetFullPath((Join-Path $rootFull $RelativePath))
    $prefix = $rootFull + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Resolved path escaped the source root: $RelativePath"
    }
    return $candidate
}

$legacyRoot = Resolve-RepositoryRoot -Path $LegacySourceContentRoot
$canonicalRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $CanonicalSourceContentRoot).Path)
$stagingRoot = Resolve-RepositoryRoot -Path $PSScriptRoot
if ($legacyRoot.Equals($stagingRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Legacy source and staging repositories must be different checkouts."
}
if ($canonicalRoot.Equals($stagingRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Canonical content root and staging repository must be different directories."
}

$releaseBranch = [string](Invoke-GitLines -Repository $stagingRoot -GitArgs @("branch", "--show-current") | Select-Object -First 1)
if ($releaseBranch -ne $ExpectedReleaseBranch) {
    throw "Release checkout branch is $releaseBranch; expected $ExpectedReleaseBranch."
}

$releaseRemoteMain = [string](Invoke-GitLines -Repository $stagingRoot -GitArgs @("rev-parse", "refs/remotes/origin/main") | Select-Object -First 1)
if ($releaseRemoteMain -ne $ExpectedBaseCommit) {
    throw "Release checkout origin/main is $releaseRemoteMain; expected the independently verified remote baseline $ExpectedBaseCommit."
}

& git -c "safe.directory=$stagingRoot" -C $stagingRoot merge-base --is-ancestor $ExpectedBaseCommit HEAD
if ($LASTEXITCODE -ne 0) {
    throw "Expected base $ExpectedBaseCommit is not an ancestor of the release checkout."
}

$stagingChanges = Get-WorkingTreePaths -Repository $stagingRoot
if ($stagingChanges.Count -gt 0) {
    throw "Release checkout must be clean before import. Commit the release tooling first. Pending paths: $($stagingChanges -join ', ')"
}

$manifestResolved = (Resolve-Path -LiteralPath $ManifestPath).Path
$manifestEntries = @(
    Get-Content -LiteralPath $manifestResolved |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith("#") } |
        ForEach-Object {
            $fields = @($_ -split "`t", 2)
            if ($fields.Count -ne 2) { throw "Manifest row must be '<source><TAB><relative path>': $_" }
            $sourceName = $fields[0].Trim().ToLowerInvariant()
            $relativePath = $fields[1].Trim().Replace("\", "/")
            if ($sourceName -notin @("legacy", "canonical")) { throw "Unknown manifest source '$sourceName': $_" }
            [pscustomobject]@{ Source = $sourceName; Path = $relativePath }
        }
)
if ($manifestEntries.Count -eq 0) {
    throw "Release manifest is empty: $manifestResolved"
}

$duplicateEntries = @(
    $manifestEntries |
        Group-Object { "$($_.Source)`t$($_.Path)" } |
        Where-Object Count -gt 1 |
        ForEach-Object Name
)
if ($duplicateEntries.Count -gt 0) {
    throw "Release manifest contains duplicate source/path entries: $($duplicateEntries -join ', ')"
}

$forbidden = @($manifestEntries | Where-Object { Test-ForbiddenReleasePath -RelativePath $_.Path })
if ($forbidden.Count -gt 0) {
    throw "Release manifest contains forbidden paths: $(@($forbidden | ForEach-Object Path) -join ', ')"
}

$legacyManifestPaths = @($manifestEntries | Where-Object Source -eq "legacy" | ForEach-Object Path)
$legacyChanges = Get-WorkingTreePaths -Repository $legacyRoot
$unexpectedLegacy = @($legacyChanges | Where-Object { $_ -notin $legacyManifestPaths })
$missingLegacy = @($legacyManifestPaths | Where-Object { $_ -notin $legacyChanges })
if ($unexpectedLegacy.Count -gt 0 -or $missingLegacy.Count -gt 0) {
    $parts = @()
    if ($unexpectedLegacy.Count -gt 0) { $parts += "unexpected legacy paths: $($unexpectedLegacy -join ', ')" }
    if ($missingLegacy.Count -gt 0) { $parts += "legacy manifest paths not changed: $($missingLegacy -join ', ')" }
    throw "The complete legacy three-tab/smart-lookup delta must match the explicit legacy rows; $($parts -join '; ')"
}

$validated = @()
$copied = @()
foreach ($entry in $manifestEntries) {
    $sourceRoot = if ($entry.Source -eq "legacy") { $legacyRoot } else { $canonicalRoot }
    $sourcePath = Resolve-ContainedPath -Root $sourceRoot -RelativePath $entry.Path
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Manifest path is missing or is not a file in $($entry.Source) source: $($entry.Path)"
    }

    $sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
    $validated += [pscustomobject]@{ Source = $entry.Source; Path = $entry.Path; Sha256 = $sourceHash }
    if (-not $ValidateOnly) {
        $destinationPath = Resolve-ContainedPath -Root $stagingRoot -RelativePath $entry.Path
        $destinationDirectory = Split-Path -Parent $destinationPath
        if (-not (Test-Path -LiteralPath $destinationDirectory)) {
            New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        }
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force

        $destinationHash = (Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash
        if ($sourceHash -ne $destinationHash) {
            throw "SHA-256 mismatch after copy: $($entry.Source) -> $($entry.Path)"
        }
        $copied += [pscustomobject]@{ Source = $entry.Source; Path = $entry.Path; Sha256 = $sourceHash }
    }
}

$diffCheck = @(& git -c "safe.directory=$stagingRoot" -C $stagingRoot diff --check)
if ($LASTEXITCODE -ne 0) {
    throw "git diff --check failed: $($diffCheck -join [Environment]::NewLine)"
}

[pscustomobject]@{
    LegacySourceRoot = $legacyRoot
    CanonicalSourceRoot = $canonicalRoot
    StagingRoot = $stagingRoot
    VerifiedRemoteBase = $releaseRemoteMain
    ReleaseBranch = $releaseBranch
    Mode = if ($ValidateOnly) { "validate-only" } else { "copy" }
    ValidatedCount = $validated.Count
    Validated = $validated
    CopiedCount = $copied.Count
    Copied = $copied
    DiffCheck = "passed"
} | ConvertTo-Json -Depth 5
