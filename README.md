
# Music2DB Client

Music2DB Client is a Python application that scans your music library, extracts metadata from audio files, and sends it to a Music2DB server. It supports various audio formats including MP3, FLAC, M4A, and OGG.

## Features

- Automatic music library scanning
- Metadata extraction from multiple audio formats
- Scheduled scanning at specified times
- Systemd service integration
- Health check before scanning
- Rich logging with detailed output

## Requirements

- Python 3.10 or higher
- Music2DB server running and accessible

## Installation

### From PyPI

```bash
pip install music2db-client
```

### From Source

```bash
git clone https://github.com/yourusername/music2db-client.git
cd music2db-client
pip install .
```

## Configuration

Create a configuration file at `~/.config/music2db/config.yaml`:

```yaml
music:
  path: /path/to/your/music
  scan_time: "04:00"  # Daily scan time
  extensions: [".mp3", ".flac", ".m4a", ".ogg"]

music_db:
  url: http://localhost
  port: 5005
  one_track_endpoint: "/add_track"
  many_tracks_endpoint: "/add_tracks"

logging:
  level: "INFO"  # or "DEBUG" for more detailed output
  format: "%(message)s"
  date_format: "%X"
  markup: true
  rich_tracebacks: true
  show_time: true
  show_path: false
```

## Running as a Service

### Install Systemd Service

```bash
# Install service file
~/.local/lib/python3.*/site-packages/music2db_client/systemd/install.sh

# Enable and start service
systemctl --user enable music2db
systemctl --user start music2db
```


## Manual Usage

You can also run the client manually:

```bash
# Start the client
music2db

# Show metadata for a specific file
music2db-show-metadata /path/to/music/file.mp3
```

## Development

```bash
# Clone repository
git clone https://github.com/yourusername/music2db-client.git

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Check code style
flake8
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
