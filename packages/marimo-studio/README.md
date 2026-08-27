<p align="center"><strong>Tune your notebook for every audience.</strong></p>

Marimo Studio turns one reactive, reproducible
[marimo](https://marimo.io/) notebook into custom web views. Each view can use
any frontend stack and toolchain while sharing the notebook's data,
transformations, controls, and reactive execution.

Install Studio and create a view:

```console
uvx marimo-studio view create dashboard --target analysis.py
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Choose **Develop** to work on notebook code, frontend source, and the rendered
view in one session.

Read the [Marimo Studio documentation](https://marimo-team.github.io/marimo-studio/)
for frontend authoring, notebook results, validation, export, and extension
development.

## License

Marimo Studio is licensed under the
[Apache License 2.0](https://github.com/marimo-team/marimo-studio/blob/main/LICENSE).
