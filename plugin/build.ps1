# Builds the importer plugin and its installable zip (plugin/sw2sc.zip) with all CPU cores.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
cargo build -j $env:NUMBER_OF_PROCESSORS --release --target wasm32-unknown-unknown -p sw2sc-plugin
wasm-tools component new target/wasm32-unknown-unknown/release/sw2sc_plugin.wasm -o package/sw2sc/sw2sc.wasm
if (Test-Path sw2sc.zip) { Remove-Item sw2sc.zip }
Compress-Archive -Path package/sw2sc/plugin.json, package/sw2sc/sw2sc.wasm -DestinationPath sw2sc.zip
& "C:\Program Files\SolidCraft\solidcraft-cli.exe" plugin check sw2sc.zip
