#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Create systemd user directory if it doesn't exist
mkdir -p "${HOME}/.config/systemd/user/"

# Copy service file to user's systemd directory
cp "${SCRIPT_DIR}/music2db.service" "${HOME}/.config/systemd/user/"

# Make sure the service file has correct permissions
chmod 644 "${HOME}/.config/systemd/user/music2db.service"

# Reload systemd daemon
systemctl --user daemon-reload

echo "Music2DB service has been installed successfully!"
echo
echo "To enable and start the service, run:"
echo "systemctl --user enable music2db"
echo "systemctl --user start music2db"
echo
echo "To check the service status:"
echo "systemctl --user status music2db"
echo
echo "To view logs:"
echo "journalctl --user -u music2db"