#dns-cloudflare-mpy

## Prerequisites

- `uv`

## Initialization

### Project Dependencies

To initialize the project

`uv sync`

then activate with:

`source .venv/bin/activate`

### MicroPython Stubs

With the environment activated, install the Stubs with

`pip install -U micropython-esp32-stubs==1.26.0.post1 --target typings --no-user`

Create a `.vscode` folder with a `settings.json` files:

```json
{
    "python.languageServer": "Pylance",
    "python.analysis.typeCheckingMode": "basic",
    "python.analysis.diagnosticSeverityOverrides": {
    "reportMissingModuleSource": "none"
    },
    "python.analysis.typeshedPaths": [
        "typings"
    ],
} 
```

## Installation on ESP32

Using mpremote, copy the files inside the src folder, excluding the `egg-info` folder. The following code should work.

```bash
cd src
mpremote fs cp -r . :/
```

