"""Build a per-user installer from a verified DeskPilot Windows payload."""

import argparse
import importlib.util
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("package_windows", ROOT / "scripts/package-windows.py")
package_windows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_windows)


def validate_payload(package):
    package = package.resolve()
    package_windows.audit(package)
    info = json.loads((package / "build-info.json").read_text(encoding="utf-8"))
    checks = json.loads((package.parent / "self-test.json").read_text(encoding="utf-8"))
    if not info.get("packaged_self_test_passed") or not checks.get("ok") or not checks.get("frozen"):
        raise ValueError("Payload must have passed its frozen self-test")
    if not checks.get("checks") or not all(check.get("ok") for check in checks["checks"].values()):
        raise ValueError("Payload contains failed self-test checks")
    expected = json.loads((package.parent / "files-sha256.json").read_text(encoding="utf-8"))
    actual = {}
    for path in package.rglob("*"):
        # Reject links/junctions so compilation cannot copy files outside the audit.
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Payload must not contain filesystem links")
        if path.is_file():
            if not path.resolve().is_relative_to(package):
                raise ValueError("Payload file escapes the package")
            actual[path.relative_to(package).as_posix()] = package_windows.sha256(path)
    if actual != expected:
        raise ValueError("Payload file inventory or SHA-256 mismatch")
    if "DeskPilot.exe" not in actual:
        raise ValueError("Payload has no DeskPilot.exe")
    # Older DP-032 executables lack the installer lifetime guard. Require a new
    # build and exact source provenance before wrapping it in an installer.
    if info.get("source_sha256") != package_windows.source_fingerprint():
        raise ValueError("Payload is stale; rebuild Windows payload from the current source first")
    return info


def compile_installer(package, output, compiler, build_id, *, validation=False, version="0.1.0"):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,70}", build_id):
        raise ValueError("Invalid build ID")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid version")
    if not validation and version != "0.1.0":
        raise ValueError("Production test installer must match the project version")
    output.mkdir(parents=True, exist_ok=False)
    args = [
        str(compiler), "/Qp", f"/DPackageDir={package}", f"/DOutputDir={output}",
        f"/DBuildId={build_id}", f"/DAppVersion={version}",
    ]
    if validation:
        args.append("/DValidationBuild=1")
    args.append(str(ROOT / "packaging/DeskPilot.iss"))
    with (output / "compiler.log").open("w", encoding="utf-8") as log:
        subprocess.run(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    installer = output / f"DeskPilot-{version}-{build_id}-setup.exe"
    if not installer.is_file():
        raise RuntimeError("Compiler did not create the installer")
    return installer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--compiler", type=Path, default=ROOT / "build/tools/inno-6.7.3/ISCC.exe")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,70}", args.build_id):
        parser.error("Invalid build ID")
    package = ROOT / "dist" / args.build_id / "DeskPilot"
    info = validate_payload(package)
    compiler = args.compiler.resolve(strict=True)
    installer = compile_installer(package, package.parent / "installer", compiler, args.build_id)
    digest = package_windows.sha256(installer)
    (installer.parent / "SHA256SUMS.txt").write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    provenance = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "payload_build_id": info["build_id"],
        "source_sha256": info["source_sha256"],
        "installer_sha256": digest,
        "compiler_sha256": package_windows.sha256(compiler),
        "installer_recipe_sha256": package_windows.sha256(ROOT / "packaging/DeskPilot.iss"),
        "signed": False,
    }
    (installer.parent / "installer-info.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"Test installer: {installer}")
    print(f"SHA256: {digest}")


if __name__ == "__main__":
    main()
