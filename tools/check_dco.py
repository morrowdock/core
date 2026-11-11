# SPDX-License-Identifier: Apache-2.0
"""Check every contributor commit between explicitly pinned PR base/head SHAs."""

import re
import subprocess
import sys


def main(args):
    if len(args) != 2 or any(not re.fullmatch(r"[0-9a-fA-F]{40}", sha) for sha in args):
        print("Usage: check_dco.py BASE_SHA HEAD_SHA (full commit SHAs)", file=sys.stderr)
        return 2
    base, head = args
    try:
        for sha in (base, head):
            subprocess.check_output(["git", "cat-file", "-e", sha + "^{commit}"], stderr=subprocess.PIPE)
        commits = subprocess.check_output(
            ["git", "rev-list", base + ".." + head], text=True, stderr=subprocess.PIPE
        ).splitlines()
        missing = []
        for commit in commits:
            body = subprocess.check_output(
                ["git", "show", "-s", "--format=%B", commit], text=True, stderr=subprocess.PIPE
            )
            if not re.search(r"^Signed-off-by: .+ <[^<>\s]+@[^<>\s]+>$", body, re.M):
                missing.append(commit)
    except subprocess.CalledProcessError:
        print("Cannot resolve the pinned PR commit range", file=sys.stderr)
        return 2
    for commit in missing:
        print("Missing DCO sign-off: " + commit, file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
