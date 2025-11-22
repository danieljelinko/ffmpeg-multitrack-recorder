# Package Management with UV

This project uses UV for Python package management instead of pip/conda. UV is an ultra-fast Python package installer and resolver written in Rust. Dependencies are declared in `pyproject.toml` files and each repository has its own virtual environment created with `uv venv`.

Whenever you need to add a new dependency execute `uv add <package_name>`.