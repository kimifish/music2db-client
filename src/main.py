# pyright: basic
# pyright: reportAttributeAccessIssue=false

import argparse
import logging
import os
import json
import time
from pathlib import Path
from typing import Dict, Any
import schedule
import requests
from mutagen import File as MutagenFile # type: ignore
from dotenv import load_dotenv
from kimiconfig import Config
cfg = Config(use_dataclasses=True)
from rich.console import Console
from rich.logging import RichHandler
from rich.pretty import pretty_repr
from rich.traceback import install as install_rich_traceback 
from kimiUtils.killer import GracefulKiller
from utils import common_theme, log_theme

APP_NAME = "music2db"
HOME_DIR = os.path.expanduser("~")
DEFAULT_CONFIG_FILE = os.path.join(
    os.getenv("XDG_CONFIG_HOME", os.path.join(HOME_DIR, ".config")), 
    APP_NAME, 
    "config.yaml")

load_dotenv()

console = Console(record=True, theme=common_theme)
log_console = Console(record=True, theme=log_theme)

# Logging setup
logging.basicConfig(
    level=logging.NOTSET,
    format="%(message)s",
    datefmt="%X",
    handlers=[RichHandler(console=log_console, markup=True)],
)
parent_logger = logging.getLogger(APP_NAME)

for logger_name in [
    "httpx",
    "httpcore",
    "mutagen",
    "uvicorn",
    "requests",
]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

log = logging.getLogger(f"{APP_NAME}.main")
install_rich_traceback(show_locals=True)

# Configuration initialization 
cfg.update("runtime.console", console)
cfg.update("runtime.log_console", log_console)

def extract_metadata(file_path: Path) -> Dict[str, Any]:
    """Extract metadata from music file."""
    audio = MutagenFile(file_path)
    if audio is None:
        return {}
    
    metadata = {}
    
    # Handle different tag formats
    tags = audio.tags
    if hasattr(audio, 'info'):
        # Basic info
        metadata['length'] = int(audio.info.length)
    
    if tags:
        # ID3 tags (MP3)
        if hasattr(tags, 'getall'):  
            metadata['artist'] = ' & '.join(str(t.text[0]) for t in tags.getall('TPE1')) if tags.getall('TPE1') else None
            metadata['title'] = ' & '.join(str(t.text[0]) for t in tags.getall('TIT2')) if tags.getall('TIT2') else None
            metadata['album'] = ' & '.join(str(t.text[0]) for t in tags.getall('TALB')) if tags.getall('TALB') else None
            metadata['genre'] = ' & '.join(str(t.text[0]) for t in tags.getall('TCON')) if tags.getall('TCON') else None
            metadata['year'] = ' & '.join(str(t.text[0]) for t in tags.getall('TDRC')) if tags.getall('TDRC') else None
            
            # Extract tags from COMM as string
            for comm in tags.getall('COMM'):
                if comm.desc == 'LastFM tags' and comm.text:
                    metadata['tags'] = comm.text[0]
                    break
                
        # Other formats (FLAC, M4A, etc.)
        else:
            metadata['artist'] = tags.get('artist', [None])[0]
            metadata['title'] = tags.get('title', [None])[0]
            metadata['album'] = tags.get('album', [None])[0]
            metadata['genre'] = tags.get('genre', [None])[0]
            metadata['year'] = tags.get('date', [None])[0]
            
            # Try to get comments/tags from other formats
            if 'comment' in tags:
                comment = tags['comment'][0]
                if isinstance(comment, str) and 'LastFM tags:' in comment:
                    # Extract tags part after "LastFM tags:" as string
                    metadata['tags'] = comment.split('LastFM tags:')[1].strip()

    return {k: v for k, v in metadata.items() if v is not None}

def check_server_health() -> bool:
    """Check if the server is running and healthy."""
    try:
        url = f"{cfg.music_db.url}:{cfg.music_db.port}/health/"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "Server is running":
                return True
            log.error("Invalid server health response")
            return False
            
        log.error(f"Server health check failed with status code: {response.status_code}")
        return False
        
    except requests.exceptions.RequestException as e:
        log.error(f"Server health check failed: {str(e)}")
        return False

def scan_music_directory() -> None:
    """Scan music directory and send metadata to server."""
    if not check_server_health():
        log.error("Server is not healthy, skipping scan")
        return
        
    music_path = Path(cfg.music.path)
    extensions = set(cfg.music.extensions)
    
    log.info(f"Starting music directory scan: {music_path}")
    
    for file_path in music_path.rglob("*"):
        try:
            if file_path.is_symlink():
                continue
                
            if file_path.suffix.lower() in extensions:
                try:
                    metadata = extract_metadata(file_path)
                    if metadata:
                        data = {
                            "file_path": str(file_path.relative_to(music_path)),
                            "metadata": metadata
                        }
                        
                        # Send to server
                        url = f"{cfg.music_db.url}:{cfg.music_db.port}{cfg.music_db.one_track_endpoint}"
                        log.debug(f'Sending metadata for {file_path.name} to {url}: {pretty_repr(data)}')
                        response = requests.post(url, json=data)
                        
                        if response.status_code == 200:
                            log.debug(f"Successfully processed: {file_path.name}")
                        else:
                            log.error(f"Failed to send metadata for {file_path.name}: {response.status_code}")
                            
                except Exception as e:
                    log.error(f"Error processing {file_path.name}: {str(e)}")
        except Exception as e:
            log.error(f"Error accessing {file_path}: {str(e)}")


def _init_logs():
    parent_logger.setLevel(cfg.logging.level)
    if cfg.logging.level == "DEBUG":
        cfg.print_config()


def _parse_args():
    parser = argparse.ArgumentParser(prog="ai_server", description="AI Server")
    parser.add_argument(
        "-c",
        "--config",
        dest="config_file",
        default=DEFAULT_CONFIG_FILE,
        help="Configuration file location.",
    )
    return parser.parse_known_args()


def _init_config(files: list[str], unknown_args: list[str]):
    """
    Initializes the configuration by loading configuration files and passed arguments.

    Args:
        files (List[str]): List of config files.
        unknown_args (List[str]): List of arguments (unknown for argparse).
    """
    cfg.load_files(files)
    cfg.load_args(unknown_args)


def main():
    args, unknown_args = _parse_args()
    _init_config([args.config_file], unknown_args)
    _init_logs()

    log.info(f"Starting {APP_NAME}")
    
    # Schedule daily scan
    schedule.every().day.at(cfg.music.scan_time).do(scan_music_directory)
    
    # Run first scan immediately
    scan_music_directory()
    
    # Keep running until killed
    while not killer.kill_now:
        schedule.run_pending()
        time.sleep(10)

    log.info(f"Shutting down {APP_NAME}")

if __name__ == "__main__":
    # Initialization of GracefulKiller for proper application termination
    killer = GracefulKiller(kill_targets=[cfg.shutdown])
    main()
