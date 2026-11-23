# Builds the importer plugin and its installable zip (plugin/sw2sc.zip) with all CPU cores.
# The version comes from the VERSION file at the top of the repository.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python stamp_version.py
cargo build -j $env:NUMBER_OF_PROCESSORS --release --target wasm32-unknown-unknown -p sw2sc-plugin
wasm-tools component new target/wasm32-unknown-unknown/release/sw2sc_plugin.wasm -o package/sw2sc/sw2sc.wasm
if (Test-Path sw2sc.zip) { Remove-Item sw2sc.zip }
Compress-Archive -Path package/sw2sc/plugin.json, package/sw2sc/sw2sc.wasm -DestinationPath sw2sc.zip
$cli = "C:\Program Files\SolidCraft\solidcraft-cli.exe"
if (Test-Path $cli) { & $cli plugin check sw2sc.zip }
