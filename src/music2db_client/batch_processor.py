from pathlib import Path
from typing import Dict, Any, List
import logging
import requests
from rich.progress import track
from .main import extract_metadata, cfg

log = logging.getLogger(__name__)

def process_directory(directory: Path, batch_size: int = 100) -> None:
    """
    Process music files in directory in batches.
    
    Args:
        directory: Path to directory with music files
        batch_size: Number of tracks to send in one request
    """
    if not directory.exists():
        log.error(f"Directory {directory} does not exist")
        return
        
    extensions = set(cfg.music.extensions)
    tracks = []
    
    log.info(f"Starting batch processing of directory: {directory}")
    
    # Collect all music files
    music_files = [
        f for f in directory.rglob("*") 
        if f.suffix.lower() in extensions and not f.is_symlink()
    ]
    
    if not music_files:
        log.info("No music files found")
        return
        
    # Process files with progress bar
    for file_path in track(music_files, description="Processing files..."):
        try:
            metadata = extract_metadata(file_path)
            if metadata:
                tracks.append({
                    "file_path": str(file_path.relative_to(directory)),
                    "metadata": metadata
                })
                
                # Send batch when reaching batch_size
                if len(tracks) >= batch_size:
                    _send_batch(tracks)
                    tracks = []
                    
        except Exception as e:
            log.error(f"Error processing {file_path.name}: {str(e)}")
            
    # Send remaining tracks
    if tracks:
        _send_batch(tracks)
        
def _send_batch(tracks: List[Dict[str, Any]]) -> None:
    """Send batch of tracks to server."""
    try:
        url = f"{cfg.music_db.url}:{cfg.music_db.port}{cfg.music_db.many_tracks_endpoint}"
        response = requests.post(url, json=tracks)
        
        if response.status_code == 200:
            result = response.json()
            log.info(result["message"])
        else:
            log.error(f"Failed to send batch: {response.status_code}")
            
    except Exception as e:
        log.error(f"Error sending batch: {str(e)}")