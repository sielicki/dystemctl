# dystemctl

**systemd emulation for Darwin** - provides `systemctl` and `journalctl` commands on macOS using launchd.

## Installation

### Nix (recommended)

```bash
# Run directly
nix run github:sielicki/dystemctl#systemctl -- status
nix run github:sielicki/dystemctl#journalctl -- -f

# Install to profile
nix profile install github:sielicki/dystemctl

# Or add to your flake
{
  inputs.dystemctl.url = "github:sielicki/dystemctl";
}
# Then use: inputs.dystemctl.packages.${system}.default
```

For nix-darwin or home-manager, add the overlay:

```nix
{
  nixpkgs.overlays = [ inputs.dystemctl.overlays.default ];
  environment.systemPackages = [ pkgs.dystemctl ];
}
```

### Homebrew

```bash
# Add the tap
brew tap sielicki/dystemctl https://github.com/sielicki/dystemctl

# Install
brew install dystemctl
```

Or install directly from the repository:

```bash
brew install --HEAD sielicki/dystemctl/dystemctl
```

### uv/uvx

```bash
uv tool install git+https://github.com/sielicki/dystemctl.git
```

### run just once

```bash
uvx --from git+https://github.com/sielicki/dystemctl.git systemctl status -n 1 emacs
● homebrew.mxcl.emacs-plus@30 - emacs-plus@30
     Loaded: loaded (/opt/homebrew/Cellar/emacs-plus@30/30.2/homebrew.mxcl.emacs-plus@30.plist; enabled)
     Active: active (running) since Fri 2026-01-23 22:16:43; 1h 32min ago
   Main PID: 72371 (emacs)
     Memory: 424.6M
        CPU: 0.0%
    Trigger: KeepAlive

Jan 23 23:49:22 dogleg emacs[72371]: Cleaning up the recentf list...done (0 removed)
```

## Usage

### systemctl commands

```bash
# List all services
systemctl status
systemctl list-units

# Manage services
systemctl start <service>
systemctl stop <service>
systemctl restart <service>
systemctl enable <service>
systemctl disable <service>

# Check status
systemctl status <service>
systemctl is-active <service>
systemctl is-enabled <service>

# View service details
systemctl show <service>
systemctl cat <service>
```

### journalctl commands

```bash
# View logs
journalctl -u <service>
journalctl -f                    # Follow logs
journalctl --since "1 hour ago"
journalctl -n 100                # Last 100 lines

# Log management
journalctl --disk-usage
journalctl --vacuum-time 7d      # Delete logs older than 7 days
journalctl --vacuum-size 100M    # Keep logs under 100MB
```

### Additional features

```bash
# Import a systemd unit file
systemctl import myservice.service

# Export a launchd service to systemd format
systemctl export com.example.myservice -o myservice.service

# Analyze boot performance
systemctl analyze
systemctl analyze blame

# Run a transient service
systemctl run echo "hello world"

# Validate service files
systemctl verify myservice.plist
```

## Service name resolution

dystemctl supports flexible service name resolution:

```bash
# All of these work:
systemctl status com.apple.cups.cupsd
systemctl status cupsd
systemctl status cups
```

## Differences from systemd

- launchd uses on-demand activation rather than explicit dependencies
- Socket activation uses launchd's native socket support
- Timer services use `StartInterval` or `StartCalendarInterval`
- Some systemd features (cgroups, namespaces) have no macOS equivalent
- ???? hundreds more. This is a pretty big hack. But for simple muscle-memory, it's pretty usable. YMMV. `¯\_(ツ)_/¯`

## Development

```bash
# Install dev dependencies
uv sync

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=dystemctl
```

## License

MIT
