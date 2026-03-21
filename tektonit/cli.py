"""CLI for the Tekton Test Agent."""

from __future__ import annotations

import tempfile
from pathlib import Path

import click

from tektonit.generators import generate_tests
from tektonit.parser import load_all_resources, parse_tekton_yaml


def llm_options(f):
    """Common options for LLM-powered commands."""
    f = click.option(
        "--provider",
        "-p",
        default="gemini",
        type=click.Choice(["gemini", "claude", "openai"]),
        help="LLM provider (default: gemini)",
    )(f)
    f = click.option("--model", "-m", default=None, help="Model name override")(f)
    f = click.option(
        "--api-key",
        default=None,
        envvar="GEMINI_API_KEY",
        help="API key (or set GEMINI_API_KEY env var)",
    )(f)
    f = click.option(
        "--base-url",
        default=None,
        envvar="OPENAI_BASE_URL",
        help="Base URL (OpenAI-compatible only)",
    )(f)
    return f


def _make_provider(provider: str, model: str | None, api_key: str | None, base_url: str | None):
    from tektonit.llm import create_provider

    return create_provider(provider=provider, model=model, api_key=api_key, base_url=base_url)


def _progress_callback(event, **kwargs):
    """Print progress during test generation."""
    if event == "start":
        r = kwargs["resource"]
        click.echo(f"\n  [{kwargs['index'] + 1}/{kwargs['total']}] {r.kind}: {r.name}")
    elif event == "done":
        result = kwargs["result"]
        mode = result.get("mode", "generate")
        test_type = result.get("test_type", "bats")
        usage = result.get("usage")
        tokens = f" ({usage['input_tokens']}+{usage['output_tokens']} tokens)" if usage else ""
        out_path = result.get("output", "")
        passed = result.get("passed")
        fix_attempts = result.get("fix_attempts", 0)
        code_issue = result.get("code_issue")
        coverage = result.get("coverage")
        flaky = result.get("flaky", False)

        status = ""
        if passed is True:
            status = " PASS"
        elif passed is False:
            status = " FAIL"
        if fix_attempts > 0:
            status += f" (fixed after {fix_attempts} attempts)"
        if code_issue:
            status += f" [CODE ISSUE: {code_issue}]"
        if flaky:
            status += " [FLAKY]"
        if coverage:
            status += f" [cov: {coverage['test_count']}t/{coverage['branch_count']}b]"

        click.echo(f"    -> [{mode}:{test_type}]{status} {out_path}{tokens}")
    elif event == "error":
        click.echo(f"    -> ERROR: {kwargs['error']}")


@click.group()
def main():
    """Tekton Test Agent - Generate tests for Tekton Tasks, Pipelines, and StepActions."""


@main.command()
@click.argument("source", type=str)
@click.option("--branch", "-b", default="main", help="Git branch to use when cloning a repo")
@llm_options
def generate(
    source: str,
    branch: str,
    provider: str,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
):
    """Generate tests in-place inside the catalog.

    Tests are created in a sanity-check/ folder next to each resource YAML:

        tasks/my-task/0.1/sanity-check/my_task_unit-tests.bats
        tasks/my-task/0.1/sanity-check/my_task_unit-tests.py

    If sanity-check/ already has tests, proposes additional tests instead.

    SOURCE can be a local directory path or a git repository URL.
    """
    source_path = _resolve_source(source, branch)
    llm = _make_provider(provider, model, api_key, base_url)

    click.echo(f"Provider: {llm.name()}")
    click.echo(f"Scanning {source_path} for Tekton resources...")
    resources = load_all_resources(source_path)

    if not resources:
        click.echo("No Tekton resources found.")
        return

    click.echo(f"Found {len(resources)} resource(s). Generating tests in-place...\n")

    from tektonit.test_generator import generate_all_tests

    results = generate_all_tests(
        resources=resources,
        provider=llm,
        callback=_progress_callback,
    )

    # Summary
    generated = [r for r in results if r.get("mode") == "generate"]
    proposed = [r for r in results if r.get("mode") == "propose"]
    errors = [r for r in results if r.get("mode") == "error"]
    passed = [r for r in results if r.get("passed") is True]
    code_issues = [r for r in results if r.get("code_issue")]

    click.echo(f"\n{'=' * 60}")
    click.echo(f"Results: {len(generated)} generated, {len(proposed)} proposed, {len(errors)} errors")
    click.echo(f"Tests passing: {len(passed)}/{len(generated)}")
    if code_issues:
        click.echo(f"Code issues detected: {len(code_issues)}")
        for ci in code_issues:
            click.echo(f"  - {ci['resource']}: {ci['code_issue']}")

    if errors:
        click.echo("\nErrors:")
        for e in errors:
            click.echo(f"  - {e['resource']}: {e['error']}")


@main.command()
@click.argument("source", type=str)
@click.option("--branch", "-b", default="main", help="Git branch to use when cloning a repo")
def scan(source: str, branch: str):
    """Scan a source for Tekton resources and display a summary.

    SOURCE can be a local directory path or a git repository URL.
    """
    source_path = _resolve_source(source, branch)

    click.echo(f"Scanning {source_path} for Tekton resources...\n")
    resources = load_all_resources(source_path)

    if not resources:
        click.echo("No Tekton resources found.")
        return

    for r in resources:
        click.echo(f"{'=' * 60}")
        click.echo(f"Kind: {r.kind}")
        click.echo(f"Name: {r.name}")
        click.echo(f"File: {r.source_path}")
        if r.params:
            click.echo(f"Params: {len(r.params)} ({len(r.required_params)} required)")
        if r.results:
            click.echo(f"Results: {len(r.results)}")
        if r.steps:
            click.echo(f"Steps: {len(r.steps)}")
        if r.workspaces:
            click.echo(f"Workspaces: {len(r.workspaces)}")
        if r.pipeline_tasks:
            click.echo(f"Pipeline Tasks: {len(r.pipeline_tasks)}")
        if r.finally_tasks:
            click.echo(f"Finally Tasks: {len(r.finally_tasks)}")
        if r.embedded_scripts:
            click.echo(f"Embedded Scripts: {len(r.embedded_scripts)}")
        click.echo()

    click.echo(f"Total: {len(resources)} resource(s)")


@main.command(name="generate-single")
@click.argument("filepath", type=click.Path(exists=True))
@llm_options
def generate_single(
    filepath: str,
    provider: str,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
):
    """Generate tests for a single Tekton YAML file.

    Creates a sanity-check/ folder next to the YAML with unit tests.
    """
    resources = parse_tekton_yaml(filepath)
    if not resources:
        click.echo(f"No Tekton resources found in {filepath}")
        return

    llm = _make_provider(provider, model, api_key, base_url)
    click.echo(f"Provider: {llm.name()}")

    from tektonit.test_generator import generate_all_tests

    results = generate_all_tests(
        resources=resources,
        provider=llm,
        callback=_progress_callback,
    )

    generated = [r for r in results if r.get("mode") == "generate"]
    proposed = [r for r in results if r.get("mode") == "propose"]
    errors = [r for r in results if r.get("mode") == "error"]

    click.echo(f"\n{len(generated)} generated, {len(proposed)} proposed, {len(errors)} errors")


@main.command(name="generate-template")
@click.argument("source", type=str)
@click.option("--output", "-o", default="generated_tests", help="Output directory for generated tests")
@click.option("--branch", "-b", default="main", help="Git branch to use when cloning a repo")
def generate_template(source: str, output: str, branch: str):
    """Generate tests using templates (no LLM, offline mode)."""
    source_path = _resolve_source(source, branch)
    click.echo(f"Scanning {source_path} for Tekton resources...")
    resources = load_all_resources(source_path)

    if not resources:
        click.echo("No Tekton resources found.")
        return

    click.echo(f"Found {len(resources)} Tekton resource(s)")
    generated = generate_tests(resources, output)
    click.echo(f"Generated {len(generated)} test file(s) in {output}/")


def _resolve_source(source: str, branch: str) -> Path:
    """Resolve a source string to a local path, cloning if it's a git URL."""
    if source.startswith(("http://", "https://", "git@")):
        import git

        tmpdir = tempfile.mkdtemp(prefix="tektonit-")
        click.echo(f"Cloning {source} (branch: {branch})...")
        git.Repo.clone_from(source, tmpdir, branch=branch, depth=1)
        return Path(tmpdir)
    return Path(source)


if __name__ == "__main__":
    main()
