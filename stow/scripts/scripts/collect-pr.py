#!/usr/bin/env python3

import subprocess
import sys
import os
import json
from pathlib import Path

def get_current_branch():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error: Unable to determine the current branch: {e}")
        sys.exit(1)

def get_changed_files(directory, target_branch, source_branch):
    try:
        print("Fetching the latest changes from origin...")
        # Fetch the latest changes from origin
        subprocess.run(["git", "fetch", "origin"], check=True)

        print(f"Getting the list of changed files between {target_branch} (target) and {source_branch} (source)...")
        # Get the list of changed files
        result = subprocess.run(
            [
                "git", "diff", "--name-only", f"origin/{target_branch}..origin/{source_branch}",
                "--", directory
            ],
            check=True,
            stdout=subprocess.PIPE,
            text=True
        )

        changed_files = result.stdout.strip().split("\n")
        print(f"Found {len(changed_files)} changed file(s).")
        return [file for file in changed_files if file]  # Remove empty entries

    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        sys.exit(1)

def collect_changes(directory, target_branch, source_branch):
    files = get_changed_files(directory, target_branch, source_branch)
    changes = {}

    for index, file in enumerate(files, start=1):
        try:
            print(f"Processing file {index}/{len(files)}: {file}")
            # Get the diff for each file
            result = subprocess.run(
                [
                    "git", "diff", f"origin/{target_branch}..origin/{source_branch}", "--", file
                ],
                check=True,
                stdout=subprocess.PIPE,
                text=True
            )
            changes[file] = result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Error collecting changes for {file}: {e}")

    return changes

def open_changes_in_vscode_or_save(changes):
    temp_file = "changes_temp.json"
    try:
        if not changes:
            print("No changes detected. Skipping file creation and opening in Visual Studio Code.")
            return
        
        print(f"Writing changes to temporary file: {temp_file}")
        with open(temp_file, "w") as f:
            json.dump(changes, f, indent=4)
        
        print(f"File {temp_file} created. Attempting to open in Visual Studio Code...")
        # Use shell=True to make subprocess respect shell commands like 'code'
        subprocess.run(["code", temp_file], check=True)
        print(f"Successfully opened {temp_file} in Visual Studio Code. Temporary file will not be deleted automatically.")
    except FileNotFoundError:
        print("Visual Studio Code is not installed or not found in PATH.")
        save_changes_to_downloads(changes)
    except subprocess.CalledProcessError as e:
        print(f"Error opening Visual Studio Code: {e}")
        save_changes_to_downloads(changes)

def save_changes_to_downloads(changes):
    downloads_dir = Path.home() / "Downloads"
    output_file = downloads_dir / "changes.json"
    try:
        print(f"Saving changes to {output_file}...")
        with open(output_file, "w") as f:
            json.dump(changes, f, indent=4)
        print(f"Changes successfully saved to {output_file}")
    except IOError as e:
        print(f"Error saving changes to file: {e}")

if __name__ == "__main__":
    if len(sys.argv) == 2:
        directory = sys.argv[1]
        source_branch = get_current_branch()
        target_branch = "develop"
        print(f"No branches provided. Comparing the current branch '{source_branch}' to 'develop'.")
    elif len(sys.argv) == 3:
        directory = sys.argv[1]
        source_branch = sys.argv[2]
        target_branch = "develop"
    elif len(sys.argv) == 4:
        directory = sys.argv[1]
        source_branch = sys.argv[2]
        target_branch = sys.argv[3]
    else:
        print("Usage: python collect_changes.py <directory> [source_branch] [target_branch]")
        sys.exit(1)

    if not os.path.isdir(directory):
        print(f"Error: {directory} is not a valid directory")
        sys.exit(1)

    print(f"Starting to collect changes in directory: {directory}")
    print(f"Source branch (PR branch): {source_branch}, Target branch (default: develop): {target_branch}")

    changes = collect_changes(directory, target_branch, source_branch)

    if changes:
        open_changes_in_vscode_or_save(changes)
    else:
        print("No changes detected.")
