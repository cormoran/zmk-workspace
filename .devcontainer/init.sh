#!/bin/bash
cd "$(dirname "$0")/.."

echo "Setting up the development environment..."
echo "* Current directory: $(pwd)"

pre-commit install || cat /root/.cache/pre-commit/pre-commit.log
