# Contributing

Open an issue with a reproducible input, expected output, actual output, Python/OS versions and relevant configuration. Use synthetic or explicitly shareable recordings; exclude credentials, personal information and unpublished institutional data.

Install with `python -m pip install -e '.[dev]'`, run `python -m pytest`, and build the wheel with `python -m build`. Cover numerical changes and failure paths with independent expected values. Keep hardware-dependent tests opt-in and describe the exact equipment and setup.

Mark unimplemented integrations as planned. Do not present heuristic scores as measured accuracy or unit tests as a hardware validation report. Contributions are distributed under this repository's Apache 2.0 license.
