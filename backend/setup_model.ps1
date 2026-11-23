$ErrorActionPreference = "Stop"

$modelfile = Join-Path $PSScriptRoot "Modelfile"
ollama create jarvis -f $modelfile
