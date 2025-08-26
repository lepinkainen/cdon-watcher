#!/bin/bash
# make-executable.sh - Make all shell scripts executable

echo "Making all shell scripts executable..."

chmod +x quickstart.sh
chmod +x verify-installation.sh
chmod +x scripts/*.sh

echo "✓ All scripts are now executable!"
echo ""
echo "You can now run:"
echo "  ./quickstart.sh - To set up and start the tracker"
echo "  ./verify-installation.sh - To verify the installation"
