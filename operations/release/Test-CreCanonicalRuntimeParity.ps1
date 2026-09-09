[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CanonicalSourceContentRoot,

    [string]$CandidateRoot = (Join-Path $PSScriptRoot "..\..")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$canonicalRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $CanonicalSourceContentRoot).Path)
$candidateRootFull = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $CandidateRoot).Path)
if ($canonicalRoot.Equals($candidateRootFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Canonical source and release candidate must be different directories."
}

$rootFiles = @(
    ".env.example",
    ".gitignore",
    ".vercelignore",
    "web/.gitignore",
    "web/README.md",
    "web/eslint.config.mjs",
    "web/next-env.d.ts",
    "web/next.config.ts",
    "web/package-lock.json",
    "web/package.json",
    "web/tsconfig.json",
    "web/vercel.json",
    "web/vitest.config.ts"
)

function Get-DeploymentSourcePaths {
    param([Parameter(Mandatory = $true)][string]$Root)

    $paths = [Collections.Generic.List[string]]::new()
    foreach ($relativePath in $rootFiles) {
        $fullPath = Join-Path $Root $relativePath
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            throw "Required deployment source file is missing: $relativePath"
        }
        $paths.Add($relativePath.Replace("\", "/"))
    }

    foreach ($tree in @("web/src", "web/scripts")) {
        $treeRoot = Join-Path $Root $tree
        if (-not (Test-Path -LiteralPath $treeRoot -PathType Container)) {
            throw "Required deployment source tree is missing: $tree"
        }
        foreach ($file in Get-ChildItem -LiteralPath $treeRoot -Recurse -File) {
            $relativePath = $file.FullName.Substring($Root.Length).TrimStart("\", "/").Replace("\", "/")
            $paths.Add($relativePath)
        }
    }

    return @($paths | Sort-Object -Unique)
}

$canonicalPaths = @(Get-DeploymentSourcePaths -Root $canonicalRoot)
$candidatePaths = @(Get-DeploymentSourcePaths -Root $candidateRootFull)
$missing = @($canonicalPaths | Where-Object { $_ -notin $candidatePaths })
$unexpected = @($candidatePaths | Where-Object { $_ -notin $canonicalPaths })
$hashMismatch = [Collections.Generic.List[string]]::new()

foreach ($relativePath in $canonicalPaths) {
    if ($relativePath -in $missing) { continue }
    $canonicalHash = (Get-FileHash -LiteralPath (Join-Path $canonicalRoot $relativePath) -Algorithm SHA256).Hash
    $candidateHash = (Get-FileHash -LiteralPath (Join-Path $candidateRootFull $relativePath) -Algorithm SHA256).Hash
    if ($canonicalHash -ne $candidateHash) {
        $hashMismatch.Add($relativePath)
    }
}

$result = [pscustomobject]@{
    CanonicalRoot = $canonicalRoot
    CandidateRoot = $candidateRootFull
    CanonicalFileCount = $canonicalPaths.Count
    CandidateFileCount = $candidatePaths.Count
    MissingCount = $missing.Count
    MissingPaths = $missing
    UnexpectedCount = $unexpected.Count
    UnexpectedPaths = $unexpected
    HashMismatchCount = $hashMismatch.Count
    HashMismatchPaths = @($hashMismatch)
    Status = if ($missing.Count -eq 0 -and $unexpected.Count -eq 0 -and $hashMismatch.Count -eq 0) { "passed" } else { "failed" }
}
$result | ConvertTo-Json -Depth 4

if ($result.Status -ne "passed") {
    throw "Canonical runtime parity failed. Only counts and paths were emitted."
}

