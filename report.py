"""
report.py
Quick command-line report, for when you just want a terminal summary
instead of opening the dashboard. Answers: "is this system working?"

Usage:
    python report.py
"""

from dotenv import load_dotenv

load_dotenv()

import db


def main():
    db.init_db()
    stats = db.get_stats()
    tasks = db.get_all_tasks()

    print("=== Devin Automated Remediation — Run Report ===")
    print(f"Total tasks:        {stats['total']}")
    print(f"Completed:          {stats['completed']}")
    print(f"Failed:             {stats['failed']}")
    print(f"In progress:        {stats['in_progress']}")
    print(f"Queued:             {stats['queued']}")
    print(f"Success rate:       {stats['success_rate']}%")
    print(f"Avg. fix time:      {stats['avg_duration_min']} min")
    print("-" * 60)

    for t in tasks:
        icon = {"completed": "✅", "failed": "❌", "in_progress": "🔄", "queued": "⏳"}.get(t["status"], "?")
        pr = t["pr_url"] or "-"
        print(f"{icon} Issue #{t['issue_number']:<4} {t['status']:<12} PR: {pr}")


if __name__ == "__main__":
    main()
