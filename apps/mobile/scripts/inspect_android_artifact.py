#!/usr/bin/env python3
"""Inspect a Poenta Android EAS artifact (APK/AAB) after download.

The script is intentionally conservative and does not require Android SDK tools.
If aapt/aapt2/apkanalyzer are installed it will use them to decode manifest
permissions. Otherwise it still reports package contents, APK/AAB type, native
libraries, and flags obvious store-readiness issues for manual follow-up.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

SENSITIVE_PERMISSION_MARKERS = [
    "ACCESS_FINE_LOCATION",
    "ACCESS_COARSE_LOCATION",
    "CAMERA",
    "RECORD_AUDIO",
    "READ_CONTACTS",
    "WRITE_CONTACTS",
    "READ_CALENDAR",
    "WRITE_CALENDAR",
    "BLUETOOTH",
    "POST_NOTIFICATIONS",
    "READ_EXTERNAL_STORAGE",
    "WRITE_EXTERNAL_STORAGE",
    "READ_MEDIA_IMAGES",
    "READ_MEDIA_VIDEO",
    "READ_MEDIA_AUDIO",
    "AD_ID",
]


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        return p.returncode, p.stdout
    except Exception as exc:  # pragma: no cover - diagnostic script
        return 999, f"{type(exc).__name__}: {exc}"


def inspect_with_android_tool(path: Path) -> dict:
    """Best-effort manifest permission extraction using optional local tools."""
    tools = []
    if shutil.which("aapt"):
        tools.append(["aapt", "dump", "permissions", str(path)])
        tools.append(["aapt", "dump", "badging", str(path)])
    if shutil.which("apkanalyzer"):
        tools.append(["apkanalyzer", "manifest", "permissions", str(path)])
    if shutil.which("aapt2"):
        # aapt2 output formats vary; include it only as diagnostic fallback.
        tools.append(["aapt2", "dump", "packagename", str(path)])

    outputs = []
    for cmd in tools:
        code, out = run(cmd)
        outputs.append({"cmd": cmd, "exit_code": code, "output": out[:8000]})
    return {"tool_outputs": outputs}


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: inspect_android_artifact.py /path/to/poenta.apk-or.aab", file=sys.stderr)
        return 2

    path = Path(sys.argv[1]).expanduser().resolve()
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2

    report: dict = {
        "artifact": str(path),
        "bytes": path.stat().st_size,
        "kind": "aab" if path.suffix.lower() == ".aab" else "apk" if path.suffix.lower() == ".apk" else "unknown",
        "checks": [],
        "warnings": [],
    }

    if not zipfile.is_zipfile(path):
        report["warnings"].append("Artifact is not a readable ZIP/APK/AAB file")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        report["entry_count"] = len(names)
        report["has_android_manifest"] = "AndroidManifest.xml" in names or "base/manifest/AndroidManifest.xml" in names
        report["native_lib_abis"] = sorted({n.split("/")[1] for n in names if n.startswith("lib/") and len(n.split("/")) > 2})
        report["aab_modules"] = sorted({n.split("/")[0] for n in names if "/manifest/AndroidManifest.xml" in n})
        suspicious = [n for n in names if any(marker.lower() in n.lower() for marker in ["ads", "firebase", "crashlytics", "analytics"])]
        report["analytics_or_ads_named_entries_sample"] = suspicious[:50]

    tool_report = inspect_with_android_tool(path)
    report.update(tool_report)
    combined_tool_output = "\n".join(item["output"] for item in tool_report["tool_outputs"])
    found_sensitive = [p for p in SENSITIVE_PERMISSION_MARKERS if p in combined_tool_output]
    report["sensitive_permission_markers_found_by_tools"] = found_sensitive

    if not tool_report["tool_outputs"]:
        report["warnings"].append("No aapt/aapt2/apkanalyzer found; install Android SDK build tools for decoded permission verification")
    if found_sensitive:
        report["warnings"].append("Sensitive permission marker found; review AndroidManifest before store submission")
    if not report.get("has_android_manifest"):
        report["warnings"].append("AndroidManifest.xml not found at expected APK/AAB paths")

    report["checks"].append("Use this report plus a real-device smoke test before Data Safety final answers")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
