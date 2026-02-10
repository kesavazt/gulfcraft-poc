#!/usr/bin/env python
"""
CLI tool to manage users on the Gulf Craft Costing platform.

Usage:
    python backend/scripts/manage_users.py add <username> --role <admin|user>
    python backend/scripts/manage_users.py list
    python backend/scripts/manage_users.py delete <username>
    python backend/scripts/manage_users.py reset-password <username>
"""
import sys
import os
import argparse
import getpass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bcrypt
from core.database import SessionLocal, User


def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def add_user(args):
    """Register a new user."""
    username = args.username
    role = args.role

    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Error: passwords do not match.")
            return 1

    if not password:
        print("Error: password cannot be empty.")
        return 1

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"Error: user '{username}' already exists.")
            return 1

        user = User(
            username=username,
            hashed_password=hash_password(password),
            role=role,
        )
        db.add(user)
        db.commit()
        print(f"User '{username}' created successfully (role: {role}).")
        return 0
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        return 1
    finally:
        db.close()


def list_users(args):
    """List all registered users."""
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id).all()
        if not users:
            print("No users found.")
            return 0

        print(f"{'ID':<6} {'Username':<25} {'Role':<10}")
        print("-" * 41)
        for u in users:
            print(f"{u.id:<6} {u.username:<25} {u.role:<10}")
        print(f"\nTotal: {len(users)} user(s)")
        return 0
    finally:
        db.close()


def delete_user(args):
    """Delete a user."""
    username = args.username
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"Error: user '{username}' not found.")
            return 1

        if not args.yes:
            confirm = input(f"Delete user '{username}' (role: {user.role})? [y/N]: ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0

        db.delete(user)
        db.commit()
        print(f"User '{username}' deleted.")
        return 0
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        return 1
    finally:
        db.close()


def reset_password(args):
    """Reset a user's password."""
    username = args.username
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"Error: user '{username}' not found.")
            return 1

        password = args.password
        if not password:
            password = getpass.getpass("New password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Error: passwords do not match.")
                return 1

        if not password:
            print("Error: password cannot be empty.")
            return 1

        user.hashed_password = hash_password(password)
        db.commit()
        print(f"Password reset for user '{username}'.")
        return 0
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        return 1
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Manage users for the Gulf Craft Costing platform"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # add
    add_parser = subparsers.add_parser("add", help="Register a new user")
    add_parser.add_argument("username", help="Username for the new account")
    add_parser.add_argument(
        "--role",
        choices=["admin", "user"],
        default="user",
        help="User role (default: user)",
    )
    add_parser.add_argument(
        "--password", "-p",
        help="Password (will prompt interactively if omitted)",
    )
    add_parser.set_defaults(func=add_user)

    # list
    list_parser = subparsers.add_parser("list", help="List all users")
    list_parser.set_defaults(func=list_users)

    # delete
    del_parser = subparsers.add_parser("delete", help="Delete a user")
    del_parser.add_argument("username", help="Username to delete")
    del_parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip confirmation"
    )
    del_parser.set_defaults(func=delete_user)

    # reset-password
    rp_parser = subparsers.add_parser("reset-password", help="Reset a user's password")
    rp_parser.add_argument("username", help="Username to reset password for")
    rp_parser.add_argument(
        "--password", "-p",
        help="New password (will prompt interactively if omitted)",
    )
    rp_parser.set_defaults(func=reset_password)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
