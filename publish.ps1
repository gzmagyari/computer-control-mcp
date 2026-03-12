param(
    [ValidateSet("patch", "minor", "major")]
    [string]$Bump = "patch"
)

$ErrorActionPreference = "Stop"

# Read current version
$content = Get-Content pyproject.toml -Raw
$current = [regex]::Match($content, 'version = "(\d+\.\d+\.\d+)"').Groups[1].Value
$parts = $current.Split('.')
$major = [int]$parts[0]
$minor = [int]$parts[1]
$patch = [int]$parts[2]

switch ($Bump) {
    "patch" { $patch++ }
    "minor" { $minor++; $patch = 0 }
    "major" { $major++; $minor = 0; $patch = 0 }
}

$newVersion = "$major.$minor.$patch"
$content = $content -replace "version = `"$current`"", "version = `"$newVersion`""
Set-Content pyproject.toml $content -NoNewline
Write-Host "Version: $current -> $newVersion"

# Clean, build, publish
if (Test-Path dist) { Remove-Item dist -Recurse -Force }
python -m hatch build
python -m hatch publish

# Clear uv cache
uv cache clean computer-control-mcp-enhanced

Write-Host ""
Write-Host "Published $newVersion"
Write-Host "Restart Claude Code to pick up the new version."
