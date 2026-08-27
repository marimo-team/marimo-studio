# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio"]
#
# [tool.marimo-studio]
# default = "dashboard"
#
# [tool.marimo-studio.cells]
#
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App()


@app.cell
def unrelated_native_branch():
    import builtins as _native_state
    import subprocess as _native_subprocess

    _native_state.__marimo_studio_unrelated_branch__ = "executed"
    _native_subprocess.run(["native-command-only"], check=True)


@app.cell
def projected_branch():
    import builtins as _projected_state

    class RuntimeState:
        def __getitem__(self, key):
            if key == "status":
                return getattr(
                    _projected_state,
                    "__marimo_studio_unrelated_branch__",
                    "clean",
                )
            if key == "a/b":
                return "slash"
            if key == "😀":
                return "emoji"
            raise KeyError(key)

    runtime_state = RuntimeState()
    return (runtime_state,)


if __name__ == "__main__":
    app.run()
