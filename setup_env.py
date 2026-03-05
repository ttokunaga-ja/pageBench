import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="PageBench environment setup helper")
    parser.add_argument("--force", action="store_true", help="Reinstall dependencies even if cache says unchanged")
    parser.add_argument("--skip-system", action="store_true", help="Skip system package setup")
    parser.add_argument("--skip-python", action="store_true", help="Skip Python package setup")
    parser.add_argument("--check", action="store_true", help="Print status only; do not install anything")
    return parser.parse_args()


def get_state_file() -> Path:
    return Path(__file__).resolve().parent / ".setup_state.json"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run_command(command, description, check=True):
    print(f"--- {description} ---")
    try:
        subprocess.run(command, shell=True, check=check)
        print(f"Success: {description}\n")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error during {description}: {e}\n")
        return False


def is_brew_package_installed(pkg_name):
    result = subprocess.run(
        f"brew list --versions {pkg_name}",
        shell=True,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def install_brew_packages(packages, check_only=False):
    missing = [pkg for pkg in packages if not is_brew_package_installed(pkg)]
    if not missing:
        print("All Homebrew packages are already installed.")
        return True

    print(f"Missing Homebrew packages: {', '.join(missing)}")
    if check_only:
        return True

    for pkg in missing:
        ok = run_command(
            f"HOMEBREW_NO_AUTO_UPDATE=1 brew install {pkg}",
            f"Installing {pkg} via Homebrew",
        )
        if not ok:
            return False
    return True

def install_system_dependencies(check_only=False):
    os_type = platform.system()
    
    if os_type == "Darwin":  # macOS
        print("Detected macOS. Checking for Homebrew...")
        brew_check = subprocess.run("brew --version", shell=True, capture_output=True)
        if brew_check.returncode == 0:
            install_brew_packages(["poppler", "tesseract"], check_only=check_only)
        else:
            print("Warning: Homebrew not found. Please install Homebrew first: https://brew.sh/")
            
    elif os_type == "Linux":
        print("Detected Linux. Checking for apt-get...")
        if not check_only:
            run_command(
                "sudo apt-get update && sudo apt-get install -y poppler-utils tesseract-ocr libmagic-dev",
                "Installing Poppler, Tesseract, and libmagic via apt",
            )
    
    elif os_type == "Windows":
        print("Detected Windows.")
        print("Note: Please manually install the following and add them to your PATH:")
        print("1. Poppler: https://github.com/oschwartz10612/poppler-windows/releases")
        print("2. Tesseract: https://github.com/UB-Mannheim/tesseract/wiki")
    else:
        print(f"Unknown OS: {os_type}. Manual installation of Poppler/Tesseract may be required.")

def load_state(state_path: Path):
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state_path: Path, state):
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def install_python_libraries(force=False, check_only=False):
    current_dir = Path(__file__).resolve().parent
    requirements_path = current_dir / "requirements.txt"
    state_path = get_state_file()
    state = load_state(state_path)

    if requirements_path.exists():
        req_hash = file_sha256(requirements_path)
        python_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        cached_hash = state.get("requirements_hash")
        cached_python = state.get("python_version")

        if not force and cached_hash == req_hash and cached_python == python_ver:
            print("Python requirements unchanged; skipping pip install.")
            return True

        print("Python requirements changed or first setup run.")
        if check_only:
            return True

        ok = run_command(
            f"{sys.executable} -m pip install -r {requirements_path}",
            "Installing Python libraries from common_utils/requirements.txt",
        )
        if ok:
            state["requirements_hash"] = req_hash
            state["python_version"] = python_ver
            save_state(state_path, state)
        return ok

    print("common_utils/requirements.txt not found. Installing core libraries individually...")
    libs = [
        "unstructured[pdf]",
        "pypdf",
        "python-docx",
        "python-pptx",
        "python-dotenv",
        "pyyaml",
        "openai",
    ]
    if check_only:
        return True
    return run_command(
        f"{sys.executable} -m pip install " + " ".join(libs),
        "Installing core Python libraries",
    )

if __name__ == "__main__":
    args = parse_args()

    print("=== PageBench Environment Setup ===\n")

    all_ok = True

    if args.check:
        print("Check mode: validate current setup status without installing.\n")

    if not args.skip_system:
        system_ok = install_system_dependencies(check_only=args.check)
        if system_ok is False:
            all_ok = False
    else:
        print("Skipped system dependencies.")

    if not args.skip_python:
        python_ok = install_python_libraries(force=args.force, check_only=args.check)
        if python_ok is False:
            all_ok = False
    else:
        print("Skipped Python libraries.")
    
    print("=== Setup Complete ===")
    if not all_ok:
        sys.exit(1)