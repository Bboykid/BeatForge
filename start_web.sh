#!/bin/bash
cd "$(dirname "$0")"
conda run -n demucs python app.py
