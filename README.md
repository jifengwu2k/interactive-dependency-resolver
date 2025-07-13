# Interactive Dependency Resolver

A tool to interactively resolve Python wheel dependencies.

This tool is particularly useful for:

- Reproducing historical development environments
- Debugging "dependency hell" scenarios
- Creating reproducible builds

## Features

- **Interactive wheel version selection** – Users choose between available versions for each wheel.
- **Conflict detection** – Automatically checks if selected versions satisfy dependencies.
- **Layer-by-layer resolution** – Processes dependencies in BFS order, one layer at a time.
- **Rollback on conflict** – If a conflict is found, reverts to the layer where the conflicting wheel was chosen.
- **Version Compatibility**: Supports both Python 2 and 3 environments.

## Running Example

This tool is not guaranteed to succeed. Thus, you should run this tool in a **clean virtual environment** set up with venv, conda, etc. to prevent contaminating your existing environment.

### Installation

```bash
pip install interactive-dependency-resolver
```

### Resolving a Python 2.7 Data Science Stack (as of 2020-01-01)

```bash
python -m interactive_dependency_resolver numpy scipy matplotlib pandas scikit-learn opencv-python torch --date 2020-01-01
```

Sample output:

```
Resolving layer 1 requirements...

Handling requirement `matplotlib`

Getting compatible wheel versions for `matplotlib`...
Select a version for `matplotlib`:
1. 2.2.4 (released on 2019-03-01)
2. 2.2.3 (released on 2018-08-11)
...
Enter a number (1-13): 1

Getting next layer requirements from `matplotlib==2.2.4`...
```

The tool will:
1. Present available versions for each wheel
2. Guide you through version selection
3. Show added dependencies in subsequent layers

### Final Output Example:

```
Final selected versions:
numpy==1.16.6
scipy==1.2.2
matplotlib==2.2.4
pandas==0.24.2
scikit-learn==0.20.4
opencv-python==4.1.2.30
torch==1.3.1

Requirements without compatible wheels:
future
```

### For Packages Without Compatible Wheels

When the resolver shows "Requirements without compatible wheels", you must:

1. **Manually verify on PyPI (https://pypi.org/)**.
2. Check for:
   - Platform-specific wheels (may need to run on different OS)
   - Source distributions (`.tar.gz`) that can be built manually

#### Common Scenarios

**Case 1: Platform-specific wheels**

For `torch` in Python 2.7:
- Linux: Has wheels
- Windows: No wheels -> Must use Linux or build from source

**Case 2: Pure Python packages**

Like `future`:

```bash
# Can safely install from source
pip install --no-deps future==1.0.0
```

**Case 3: C-extensions without wheels**

Like `subprocess32`:

```bash
# Requires build tools
sudo apt-get install python-dev  # Debian/Ubuntu
pip install --no-deps subprocess32
```

### Installing the Resolved Environment

You **MUST** use `--no-deps` with `pip install` to prevent automatic dependency resolution:

```bash
pip install --no-deps numpy==1.16.6 scipy==1.2.2 matplotlib==2.2.4 pandas==0.24.2 scikit-learn==0.20.4 opencv-python==4.1.2.30 torch==1.3.1
pip install --no-deps future  # install from source
```

Then, you **MUST** run `pip check` and check for **hidden dependencies**:

```
matplotlib 2.2.4 requires cycler, which is not installed.
matplotlib 2.2.4 requires kiwisolver, which is not installed.
```

Use the tool to resolve these additional dependencies and repeat the verification process.

## How It Works

1. Queries PyPI JSON API for package metadata
2. Filters versions by:
   - Release date (before specified cutoff)
   - Wheel compatibility with current platform
   - Version constraints
3. Builds dependency graph layer by layer
4. Handles conflicts by rolling back decisions when necessary

## Platform Considerations

- Wheel compatibility is automatically evaluated for your current platform
- For cross-platform resolution, execute the tool on the target system

## Known Limitations

- May miss some implicit dependencies (e.g., `matplotlib`'s optional dependencies)
- Requires manual intervention for some complex dependency conflicts

## Contributing

Contributions are welcome! Please submit pull requests or open issues on GitHub.

## License

AGPL-3.0 - See [LICENSE](LICENSE) for details.