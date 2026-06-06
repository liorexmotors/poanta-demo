#!/usr/bin/env python3
"""Static regression checks for Poenta native Settings performance and language selector.

This guards the recurring regression where Settings taps become slow because every
source/topic/card row rerenders, and the language selector disappears from the
Settings window.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "App.tsx"
text = APP.read_text(encoding="utf-8")
errors: list[str] = []

checks = {
    "React memo import": r"import \{[^}]*\bmemo\b[^}]*\} from 'react';",
    "Memoized Chip": r"const\s+Chip\s*=\s*memo\(",
    "Memoized source settings rows": r"const\s+SettingsSourceRow\s*=\s*memo\(",
    "Memoized topic settings chips": r"const\s+SettingsTopicChip\s*=\s*memo\(",
    "Memoized article cards": r"const\s+ArticleCard\s*=\s*memo\(",
    "Memoized breaking cards": r"const\s+BreakingCard\s*=\s*memo\(",
    "Stable topic toggle callback": r"const\s+toggleTopic\s*=\s*useCallback\(",
    "Stable source toggle callback": r"const\s+toggleSource\s*=\s*useCallback\(",
    "Stable day setter callback": r"const\s+setSettingsDays\s*=\s*useCallback\(",
    "Settings language selector title": r"tr\('שפת האפליקציה והפיד'\)",
    "All approved language options rendered": r"LANGUAGE_OPTIONS\.map\(option =>",
    "Language choices update both draft and app prefs": r"setSettingsPrefs\(prev => \(\{ \.\.\.prev, language: lang \}\)\);\s*\n\s*setPrefs\(prev => \(\{ \.\.\.prev, language: lang \}\)\);",
}

for name, pattern in checks.items():
    if not re.search(pattern, text, re.S):
        errors.append(f"missing: {name}")

# Prevent reintroducing the slow path: settings source rows must not be inline touchables.
settings_block = re.search(r"const renderSettings = \(\) => <View[\s\S]*?</View>;\n\n  const list =", text)
if not settings_block:
    errors.append("missing renderSettings block")
else:
    block = settings_block.group(0)
    if "<SettingsSourceRow" not in block:
        errors.append("Settings source list must render SettingsSourceRow")
    if "<SettingsTopicChip" not in block:
        errors.append("Settings topics must render SettingsTopicChip")
    if re.search(r"group\.sources\.map\([\s\S]{0,220}<TouchableOpacity", block):
        errors.append("source rows still use inline TouchableOpacity map")

if errors:
    print("Settings regression checks FAILED:")
    for err in errors:
        print(f"- {err}")
    sys.exit(1)

print("Settings regression checks PASS")
