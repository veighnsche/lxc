"""Interactive configuration prompts for deployment."""

import getpass
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from .config import Config

console = Console()


def _prompt_password(prompt: str, default: str) -> str:
    """Prompt for password with hidden input and confirmation (Unix-style)."""
    while True:
        console.print(f"  [bold]{prompt}[/bold]: ", end="")
        password1 = getpass.getpass(prompt="")
        
        if not password1:
            # User pressed Enter, use default
            return default
        
        console.print(f"  [bold]Confirm {prompt.lower()}[/bold]: ", end="")
        password2 = getpass.getpass(prompt="")
        
        if password1 == password2:
            return password1
        else:
            console.print("  [red]Passwords do not match. Try again.[/red]")


def prompt_config() -> Config:
    """Prompt user for deployment configuration.
    
    Returns a Config object with user-specified values.
    Press Enter to accept defaults.
    """
    cfg = Config()
    
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Gentoo LXC Deployment Configuration[/bold cyan]\n\n"
        "Press [bold]Enter[/bold] to accept defaults, or type a new value.",
        border_style="cyan"
    ))
    console.print()
    
    # Container user
    cfg.container_user = Prompt.ask(
        "  [bold]Username[/bold] (for SSH access)",
        default=cfg.container_user
    )
    
    # Password (hidden input, Unix-style)
    cfg.default_password = _prompt_password("Password (for SSH login)", cfg.default_password)
    
    # Network configuration
    console.print()
    console.print("  [dim]── Network Configuration ──[/dim]")
    
    cfg.network.container_ip = Prompt.ask(
        "  [bold]Container IP[/bold] (must be unused on your LAN)",
        default=cfg.network.container_ip
    )
    
    cfg.network.container_gateway = Prompt.ask(
        "  [bold]Gateway IP[/bold] (your router)",
        default=cfg.network.container_gateway
    )
    
    # Rootfs size
    console.print()
    console.print("  [dim]── Storage Configuration ──[/dim]")
    
    size_gb = Prompt.ask(
        "  [bold]Rootfs size[/bold] (GB, for portage/builds/packages)",
        default=str(cfg.rootfs_image_size_mb // 1024)
    )
    cfg.rootfs_image_size_mb = int(size_gb) * 1024
    
    # Show summary
    _show_summary(cfg)
    
    if not Confirm.ask("  Proceed with deployment?", default=True):
        raise typer.Exit(0)
    
    return cfg


def _show_summary(cfg: Config) -> None:
    """Display configuration summary table."""
    console.print()
    table = Table(title="Deployment Configuration", border_style="green")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Username", cfg.container_user)
    table.add_row("Password", "********")
    table.add_row("Container IP", cfg.network.container_ip)
    table.add_row("Gateway", cfg.network.container_gateway)
    table.add_row("Rootfs Size", f"{cfg.rootfs_image_size_mb // 1024} GB")
    table.add_row("Network Mode", "IPVLAN L2 + Hardening")
    console.print(table)
    console.print()
