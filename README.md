# Prerequisites

- `uv`

# Initialization

## Project Dependencies

To initialize the project, create a virtual environment with

`uv venv`

then activate with

` .venv\Scripts\activate`

and install the dependencies with

`uv pip install -r pyproject.toml`

## MicroPython Stubs

With the environment activated, install the Stubs with

`pip install -U micropython-esp32-stubs==1.26.0.post1 --target typings --no-user`

Create a `.vscode` folder with a `settings.json` files:

```
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