# AGENTS.md - Subtitle Studio Development Guide

This document provides guidance for AI agents working with the Subtitle Studio codebase.

## Project Overview

Subtitle Studio is a Python desktop application for subtitle editing, voice mapping, and TTS audio generation. Built with customtkinter.

## Build Commands

### Running the Application
```bash
# Development mode (requires .venv with dependencies)
.venv/bin/python studio.py

# Or with system Python
python studio.py
```

### Testing

Tests use Python's built-in `unittest` framework (not pytest).

```bash
# Run all tests
python -m unittest discover -s tests -p "*test*.py" -v

# Run a single test file
python -m unittest tests/test_project.py -v

# Run a specific test class
python -m unittest tests.test_project.TestProject -v

# Run a specific test method
python -m unittest tests.test_project.TestProject.test_create_new_project_success -v
```

### Building for Distribution

```bash
# Build with PyInstaller
./build_pyinstaller.sh

# Build and install to ~/Applications
./build_pyinstaller.sh install
```

The build process uses `build_app.py` to prepare resources, then runs PyInstaller with `SubtitleStudio.spec`.

## Code Style Guidelines

### Python Version
- Target: Python 3.x
- All modules should be compatible with both dev and frozen (PyInstaller) modes
- Check for `getattr(sys, 'frozen', False)` when accessing runtime paths

### Type Hints
- Use `typing` module for type annotations
- Common imports: `Optional`, `List`, `Dict`, `Tuple`, `Callable`, `Any`
- Prefer explicit return types on public methods

### Imports
```python
# Standard library first
import os
import sys
from pathlib import Path
from typing import List, Optional, Dict
import re
import json

# Third-party libraries
import customtkinter as ctk
from dataclasses import dataclass, field

# Local application imports (absolute paths)
from app.entity import Line, PatternItem
from app.logger import Logger
from ui.menu import AppMenu
```

### Naming Conventions
- **Classes**: PascalCase (e.g., `SubtitleStudioApp`, `PatternManagerWindow`)
- **Functions/methods**: snake_case (e.g., `apply_patterns`, `set_project_path`)
- **Private methods**: underscore prefix (e.g., `_start_threads`, `_ensure_csv_cache`)
- **Constants**: SCREAMING_SNAKE_CASE (e.g., `APP_CONFIG`, `CSV_FIELDNAMES`)
- **Dataclass fields**: snake_case (e.g., `original_text`, `audio_filename`)

### Data Models
Uses `@dataclass` for data structures with helper methods:
```python
@dataclass
class Line:
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    original_text: str = ""
    audio_status: str = ""

    def get_text(self) -> str:
        if self.text is None:
            return self.original_text
        return self.text
```

### Error Handling
- Use try/except with specific exception types when possible
- Use `Logger.error()` for logging errors with context
- For UI errors, use `messagebox.showerror()` for user-facing errors
- Wrap regex compilation in try/except with user-friendly error messages

### Logging
Use the custom `Logger` class:
```python
from app.logger import Logger

Logger.info("Message", context="Component")
Logger.debug("Debug info", context="Worker")
Logger.error("Something failed", context="IO", to_console=True)
```

### Tkinter/custkomtkinter Patterns
- Mock tkinter when testing modules that import it
- Use `MagicMock()` for tkinter modules in test setUp
- UI windows inherit from `CTkToplevel` or `CTkFrame`

### Testing Patterns
- Mock tkinter modules before importing application modules:
```python
import sys
sys.modules['tkinter'] = MagicMock()
sys.modules['tkinter.filedialog'] = MagicMock()
from app.project import create_new_project
```
- Use `unittest.mock` for patching functions
- Use `mock_open` for file operations
- Test class naming: `Test<ModuleName>` or `Test<Feature>`
- Test method naming: `test_<behavior>`

### File Structure
```
app/           # Core business logic
  entity.py    # Data models (Line, PatternItem)
  project.py   # Project management
  worker.py    # Background task processing
  io.py        # File I/O, CSV handling
  patterns.py  # Regex pattern management
  utils.py     # Helper functions
  generation.py # TTS generation logic

ui/            # GUI components
  menu.py      # Application menu
  *.py         # Window/dialog implementations

tests/         # Unit tests
  test_*.py    # One test file per module
```

### Common Patterns

**Path handling for dev vs frozen:**
```python
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    home = Path.home()
    application_path = home / '.config'
```

**Worker callback pattern:**
```python
def on_complete(result):
    pass  # Handle result on main thread

def on_error(exception):
    pass  # Handle error

def on_progress(percent: int, message: str):
    pass  # Update progress UI

worker.add_task(func, arg1, arg2, on_complete=on_complete, on_error=on_error)
```

**Status flags:**
- Line statuses: `MISSING`, `ERROR`, `OK`, `SHORT`, `DONE`
- Audio flags: `PENDING`, `OK`, `HALLUCINATION`

### Configuration
- Global config: `~/.config/subtitle-studio.json` (dev) or `app_dir/subtitle-studio.json` (frozen)
- Project files: `.json` format with structured data
- CSV export: `csv.DictReader`/`csv.DictWriter` with UTF-8 encoding
