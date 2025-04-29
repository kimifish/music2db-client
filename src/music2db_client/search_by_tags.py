#!/usr/bin/env python3

import argparse
import requests
from urllib.parse import quote, urlencode
from rich.console import Console
from rich.table import Table
from rich.text import Text

def format_match_level(match_level: float) -> Text:
    """Format match level with color based on percentage."""
    percentage = float(match_level)
    if percentage >= 0.8:
        return Text(f"{percentage:.1%}", style="bright_green")
    elif percentage >= 0.6:
        return Text(f"{percentage:.1%}", style="green")
    elif percentage >= 0.4:
        return Text(f"{percentage:.1%}", style="yellow")
    elif percentage >= 0.2:
        return Text(f"{percentage:.1%}", style="orange3")
    else:
        return Text(f"{percentage:.1%}", style="red")

def main():
    parser = argparse.ArgumentParser(description="Search music tracks by tags")
    parser.add_argument(
        "tags", 
        help="Tags to search for (comma-separated)")
    parser.add_argument(
        "-l", 
        "--limit", 
        type=int, 
        default=20, 
        help="Maximum number of results (default: 20)")
    parser.add_argument(
        "-m", 
        "--max-distance", 
        type=float, 
        default=1.0,
        help="Maximum distance (0.0 to 2.0, default: 1.0)")
    parser.add_argument(
        "--url", 
        default="http://kimihome.lan:5005", 
        help="Server URL (default: http://localhost:5005)")
    args = parser.parse_args()

    if not 0.0 <= args.max_distance <= 2.0:
        console = Console()
        console.print("\n[red]Error: max-distance must be between 0.0 and 2.0[/]")
        return 1

    # Prepare query parameters
    params = {
        'tags': args.tags,
        'limit': args.limit,
        'max_distance': args.max_distance
    }
    url = f"{args.url}/search_tracks/?{urlencode(params)}"

    try:
        response = requests.get(url)
        response.raise_for_status()
        results = response.json()

        console = Console()
        
        if not results:
            console.print("\n[yellow]No tracks found matching these tags[/]")
            return

        table = Table(show_header=True, header_style="bold blue", 
                     title=f"Search results for tags: {args.tags}",
                     title_style="bold blue")
        table.add_column("№", style="dim", width=4)
        table.add_column("Distance", justify="right", width=8)
        table.add_column("Track Path", width=None)  # None means flexible width

        # Sort results by match level in descending order
        if isinstance(results[0], dict):
            results.sort(key=lambda x: x['distance'], reverse=True)

        for idx, result in enumerate(results, 1):
            if isinstance(result, dict):
                path = result['path']
                match_level = format_match_level(result['distance'])
            else:
                path = result
                match_level = Text("N/A", style="dim")
            
            table.add_row(
                str(idx),
                match_level,
                Text(path, style="bright_white" if idx == 1 else None)
            )

        console.print("\n")
        console.print(table)
        console.print("\n")

    except requests.exceptions.RequestException as e:
        console = Console()
        console.print(f"\n[red]Error connecting to server:[/] {str(e)}")
        return 1

if __name__ == "__main__":
    main()