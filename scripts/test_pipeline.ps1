$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    py -3 -m unittest discover -s tests -v
}
finally {
    Pop-Location
}
