import pathlib
import subprocess


REPO = pathlib.Path(__file__).resolve().parents[1]
# Tokens are assembled from fragments so the literals never appear in this
# file's own source. That keeps the public history-scrub (git filter-repo)
# from rewriting this guard — which would change the shipping tree and break
# the "tree unchanged" publish invariant. Do not inline these back.
BANNED = [
    "aris" + "-space",
    "shadow" + "_brain",
    "/Vol" + "umes/",
    "MEMORY" + "_BANK",
    "leaves" + "ley",
    "Val" + "halla",
]


def test_no_private_tokens_in_tree():
    hits = []
    for token in BANNED:
        result = subprocess.run(
            ["git", "grep", "-niI", "--", token, ".", ":(exclude)tests/**"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        output = "\n".join(
            line
            for line in result.stdout.splitlines()
            if "tests/test_scrub_guard.py" not in line
        )
        if output.strip():
            hits.append(output)

    assert not hits, "private token leak:\n" + "\n".join(hits)
