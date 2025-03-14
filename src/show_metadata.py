#!/usr/bin/env python3

import argparse
from pathlib import Path
from rich.console import Console
from rich.pretty import Pretty
from main import extract_metadata

def main():
    parser = argparse.ArgumentParser(description="Show metadata that would be sent to server for a music file")
    parser.add_argument("file", type=Path, help="Path to music file")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"Error: File {args.file} does not exist")
        return 1

    metadata = extract_metadata(args.file)
    request_data = {
        "file_path": args.file.name,
        "metadata": metadata
    }

    console = Console()
    console.print("\n[bold blue]Request that would be sent to server:[/]")
    console.print(Pretty(request_data, expand_all=True))

if __name__ == "__main__":
    main()