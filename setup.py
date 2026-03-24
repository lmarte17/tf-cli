from pathlib import Path

from setuptools import find_packages, setup


ROOT = Path(__file__).resolve().parent

setup(
    name="tinyfish-cli",
    version="0.1.0",
    description="Agent-friendly TinyFish CLI built from the public API docs and OpenAPI spec.",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="Luis Marte",
    python_requires=">=3.9",
    url="https://github.com/lmarte17/tf-cli",
    project_urls={
        "Documentation": "https://github.com/lmarte17/tf-cli#readme",
        "Source": "https://github.com/lmarte17/tf-cli",
        "Issues": "https://github.com/lmarte17/tf-cli/issues",
        "TinyFish Docs": "https://docs.tinyfish.ai/api-reference/automation/run-browser-automation-with-sse-streaming",
    },
    package_dir={"": "src"},
    packages=find_packages("src"),
    include_package_data=True,
    entry_points={"console_scripts": ["tinyfish=tinyfish_cli.cli:main"]},
)
