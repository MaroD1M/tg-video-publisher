"""
Admin tools CLI.
Usage: docker exec -it tg-video-publisher python -m app.cli reset-admin --interactive
"""

import argparse
import asyncio
from getpass import getpass
from app.auth.utils import reset_admin_password


def main():
    parser = argparse.ArgumentParser(description="TG视频发布助手 admin CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    reset = sub.add_parser("reset-admin", help="Reset admin password")
    reset.add_argument("--password", help="New password")
    reset.add_argument("--interactive", action="store_true", help="Interactive input")

    args = parser.parse_args()

    if args.cmd == "reset-admin":
        if args.interactive:
            pwd = getpass("New password: ")
            confirm = getpass("Confirm password: ")
            if pwd != confirm:
                print("Passwords do not match.")
                return
        elif args.password:
            pwd = args.password
        else:
            parser.error("Either --password or --interactive is required")

        asyncio.run(reset_admin_password(pwd))
        print("Admin password reset successfully.")


if __name__ == "__main__":
    main()
