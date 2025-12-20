"""Console utilities and logging functions."""

import sys

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table
    from rich.panel import Panel
    import typer
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install rich typer httpx")
    sys.exit(1)

console = Console()


def log(msg: str) -> None:
    """Log a message."""
    console.print(f"[dim]>[/dim] {msg}")


def log_ok(msg: str) -> None:
    """Log a success message."""
    console.print(f"[green]✓[/green] {msg}")


def log_warn(msg: str) -> None:
    """Log a warning message."""
    console.print(f"[yellow]⚠[/yellow] {msg}", style="yellow")


def log_err(msg: str) -> None:
    """Log an error message."""
    console.print(f"[red]✗[/red] {msg}", style="red")


def die(msg: str) -> None:
    """Log error and exit."""
    log_err(msg)
    raise typer.Exit(1)


def step_header(step: int, total: int, title: str) -> None:
    """Print a step header."""
    console.print()
    console.rule(f"[bold blue]Step {step}/{total}: {title}[/bold blue]")
    console.print()
