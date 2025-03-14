#!/usr/bin/env python3

import argparse
import requests
from urllib.parse import quote
from rich.console import Console
from rich.table import Table

def main():
    parser = argparse.ArgumentParser(description="Search music tracks by tags")
    parser.add_argument("tags", help="Tags to search for (comma-separated)")
    parser.add_argument("-l", "--limit", type=int, default=5, help="Maximum number of results (default: 5)")
    parser.add_argument("--url", default="http://kimihome.lan:5005", help="Server URL (default: http://localhost:5005)")
    args = parser.parse_args()

    # Prepare the URL with encoded tags
    encoded_tags = quote(args.tags)
    url = f"{args.url}/search_tracks/?tags={encoded_tags}&limit={args.limit}"

    try:
        response = requests.get(url)
        response.raise_for_status()
        tracks = response.json()

        console = Console()
        
        if not tracks:
            console.print("\n[yellow]No tracks found matching these tags[/]")
            return

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("№", style="dim")
        table.add_column("Track Path")

        for idx, track in enumerate(tracks, 1):
            table.add_row(str(idx), track)

        console.print("\n[bold blue]Found tracks:[/]")
        console.print(table)

    except requests.exceptions.RequestException as e:
        console = Console()
        console.print(f"\n[red]Error connecting to server:[/] {str(e)}")
        return 1

if __name__ == "__main__":
    main()