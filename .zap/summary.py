"""Turn a ZAP JSON report into a Markdown table (GitHub Actions job summary).

usage: python3 .zap/summary.py .zap/report/zap-report.json >> "$GITHUB_STEP_SUMMARY"
"""

import json
import re
import sys

RISK_ICON = {"3": "🔴 High", "2": "🟠 Medium", "1": "🟡 Low", "0": "🔵 Info"}


def main(path):
    with open(path) as f:
        report = json.load(f)
    alerts = [a for site in report.get("site", []) for a in site.get("alerts", [])]
    alerts.sort(key=lambda a: -int(a["riskcode"]))

    print("### OWASP ZAP findings\n")
    if not alerts:
        print("No alerts. ✅")
        return
    print("| Risk | Alert | ZAP rule | Pages | Example |")
    print("|---|---|---|---|---|")
    for a in alerts:
        # collapse ids so /content/<uuid> pages count once
        urls = sorted({re.sub(r"[0-9a-f-]{36}", "<id>", i["uri"]) for i in a["instances"]})
        print(
            f"| {RISK_ICON.get(a['riskcode'], a['riskcode'])} | {a['name']} "
            f"| [{a['pluginid']}](https://www.zaproxy.org/docs/alerts/{a['pluginid']}/) "
            f"| {len(urls)} | `{urls[0]}` |"
        )
    print("\nFull HTML report: see the **zap-report** artifact of this run.")


if __name__ == "__main__":
    main(sys.argv[1])
