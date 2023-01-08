import argparse
import collections
import datetime
import subprocess
from typing import TypedDict

from miniscreen import MiniScreen, read_one_keystroke


parser = argparse.ArgumentParser()
parser.add_argument("revision_range")


class Commit(TypedDict):
    tree: str
    parents: list[str]
    author_name: str
    author_email: str
    author_date: str
    committer_name: str
    committer_email: str
    committer_date: str
    subject: str
    body: str


def git_cat_file(sha: str) -> tuple[str, bytes]:
    d = subprocess.check_output("git cat-file --batch", input=sha.encode(), shell=True)
    first_line, nl, rest = d.partition(b"\n")
    assert nl
    oid, type, size_str = first_line.decode().split()
    size = int(size_str)
    assert oid == sha, (oid, sha)
    assert len(rest) == size + 1, (len(rest), size, rest[:100])
    return type, rest


def parse_name_email_date(name_email_date: bytes) -> tuple[str, str, str]:
    assert name_email_date.count(b" ") >= 3
    name, email, timestamp_s, tz_s = name_email_date.decode().rsplit(" ", 3)

    assert email.startswith("<")
    assert email.endswith(">")
    email = email[1:-1]

    timestamp = int(timestamp_s)
    dt = str(datetime.datetime.fromtimestamp(timestamp))

    return name, email, dt


def git_get_commit(sha: str) -> Commit:
    type, data = git_cat_file(sha)
    headers_b, sep_b, message_b = data.partition(b"\n\n")
    assert sep_b
    parents: list[str] = []
    headers: dict[bytes, bytes] = {}
    for line in headers_b.split(b"\n"):
        k, sep_b, v = line.partition(b" ")
        assert sep_b, line
        if k == b"parent":
            parents.append(v.decode())
        else:
            assert k not in headers, (k, headers_b)
            headers[k] = v
    message = message_b.decode()
    subject, sep, body = message.strip("\n").partition("\n\n")
    body = body.strip("\n")
    subject = subject.replace("\n", " ")
    author_name, author_email, author_date = parse_name_email_date(
        headers.pop(b"author")
    )
    committer_name, committer_email, committer_date = parse_name_email_date(
        headers.pop(b"committer")
    )
    tree = headers.pop(b"tree").decode()
    return {
        "tree": tree,
        "parents": parents,
        "author_name": author_name,
        "author_email": author_email,
        "author_date": author_date,
        "committer_name": committer_name,
        "committer_email": committer_email,
        "committer_date": committer_date,
        "subject": subject,
        "body": body,
    }


DiffStat = tuple[int, int]  # added, removed
LineSource = tuple[str, str, int]  # sha, file, line


class Blame(TypedDict):
    totaldiffstat: DiffStat
    filediffstat: dict[str, DiffStat]
    filelines: dict[str, list[LineSource]]


def sha_has_filename(sha: str, filename: str) -> bool:
    try:
        subprocess.check_output(
            ("git", "rev-parse", "--quiet", "--verify", f"{sha}:{filename}")
        )
    except subprocess.CalledProcessError:
        return False
    return True


def git_show_numstat(sha: str) -> dict[str, DiffStat]:
    numstat = subprocess.check_output(
        ("git", "show", "--format=", "--numstat", sha),
    )
    filediffstat: dict[str, DiffStat] = {}
    if not numstat.strip(b"\n"):
        return filediffstat
    for line in numstat.strip(b"\n").split(b"\n"):
        assert line.count(b"\t") >= 2
        added, removed, filename = line.decode().split("\t", 2)
        filediffstat[filename] = (int(added), int(removed))
    return filediffstat


def git_blame(sha: str, filename: str) -> list[tuple[LineSource, bytes]]:
    if not sha_has_filename(sha, filename):
        return []
    blame_b = subprocess.check_output(
        ("git", "blame", "--porcelain", sha, "--", filename),
    )
    blame_output_lines = iter(blame_b.strip(b"\n").split(b"\n"))
    lines: list[tuple[LineSource, bytes]] = []
    linedata_for_sha: dict[bytes, dict[bytes, bytes]] = {}
    for lineno, headerline in enumerate(blame_output_lines, 1):
        assert headerline.count(b" ") >= 2
        blamesha, blameline, finalline, *_ignore = headerline.split(b" ", 3)
        linedata: dict[bytes, bytes] = {}
        for extraline in blame_output_lines:
            if extraline.startswith(b"\t"):
                contents = extraline[1:] + b"\n"
                break
            k_b, sep_b, v_b = extraline.partition(b" ")
            assert sep_b
            linedata[k_b] = v_b
        else:
            raise Exception("Unexpected EOF in git blame")
        if b"filename" in linedata:
            blamefile = linedata[b"filename"]
            linedata_for_sha[blamesha] = linedata
        else:
            assert blamesha in linedata_for_sha, (
                sha,
                filename,
                blamesha,
                len(lines),
                linedata,
            )
            blamefile = linedata_for_sha[blamesha][b"filename"]
        lines.append(((blamesha.decode(), blamefile.decode(), int(blameline)), contents))
    return lines


def sum_diffstats(filediffstat: dict[str, DiffStat]) -> DiffStat:
    totaladded = 0
    totalremoved = 0
    for filename, (added, removed) in filediffstat.items():
        totaladded += added
        totalremoved += removed
    return totaladded, totalremoved


def compute_blame_data(sha: str) -> Blame:
    filediffstat = git_show_numstat(sha)
    totaldiffstat = sum_diffstats(filediffstat)

    filelines: dict[str, list[LineSource]] = {}
    for filename, (added, removed) in filediffstat.items():
        lines = git_blame(sha, filename)
        filelines[filename] = [
            line_source
            for line_source, contents in lines
            # Skip if line only contains delimiters and whitespace
            if contents.strip(b" \t\n\r<>(){}[],;")
        ]
    return {
        "totaldiffstat": (totaladded, totalremoved),
        "filediffstat": filediffstat,
        "filelines": filelines,
    }


def main() -> None:
    args = parser.parse_args()
    objects = subprocess.check_output(
        "git rev-list --stdin",
        input=args.revision_range,
        shell=True,
        universal_newlines=True,
    ).split()[::-1]
    filediffstats: dict[str, dict[str, DiffStat]] = {}
    file_to_commits: dict[str, list[str]] = {}
    # [sha1][file][sha2] is a set of line numbers of sha1:file
    # that are present in sha2
    commit_commit_lines: dict[str, dict[str, dict[str, set[int]]]] = {
        o: {} for o in objects
    }
    # [sha1][file][line] is the sha2 that removes the line
    commit_lines_remove: dict[str, dict[str, dict[int, str | None]]] = {
        o: {} for o in objects
    }
    commitlistheight = 30
    commits: dict[str, Commit] = {}
    file_blames: dict[str, list[tuple[str, list[tuple[LineSource, bytes]]]]] = {}
    current = len(objects) - 1, 0
    shalen = 10
    with MiniScreen() as ms:
        while True:
            lines = []
            for i in range(commitlistheight):
                object_index = current[0] - commitlistheight + 1 + i
                if object_index < 0:
                    lines.append("")
                    continue
                sha = objects[object_index]
                try:
                    c = commits[sha]
                except KeyError:
                    ms.set_line(f'git log -1 {sha}')
                    c = commits[sha] = git_get_commit(sha)
                    ms.set_line("")
                star = "*" if object_index == current[0] else " "
                lines.append(f'{star} {sha[:shalen]} {c["subject"]}')

            sha = objects[current[0]]
            c = commits[sha]
            indent = "  " + " " * shalen
            commitline = f'{indent} {c["author_name"]} {c["author_date"]}'
            blamedesc = ""
            removedesc = f"{indent} Loading blame"
            if sha not in filediffstats:
                ms.set_window(lines + [commitline, blamedesc, removedesc])
            while sha not in filediffstats:
                nextsha = objects[-1 - len(filediffstats)]
                ms.set_line(f'git show --numstat {nextsha}')
                filediffstats[nextsha] = git_show_numstat(nextsha)
                for filename in filediffstats[nextsha]:
                    ms.set_line(f'git blame {nextsha} -- {filename}')
                    blame_lines = git_blame(nextsha, filename)
                    file_blames.setdefault(filename, []).append((nextsha, blame_lines))
                    childsha = file_to_commits[filename][-1] if filename in file_to_commits else None
                    file_to_commits.setdefault(filename, []).append(nextsha)
                    for line_source, contents in blame_lines:
                        # Skip if line only contains delimiters and whitespace
                        if not contents.strip(b" \t\n\r<>(){}[],;"):
                            continue
                        blamesha, blamefile, blameline = line_source
                        try:
                            blamecommitlines = commit_commit_lines[blamesha]
                        except KeyError:
                            continue
                        blamecommitlines.setdefault(blamefile, {}).setdefault(
                            nextsha, set()
                        ).add(blameline)
                        commit_lines_remove[blamesha].setdefault(
                            blamefile, {}
                        ).setdefault(blameline, childsha)
                ms.set_line("")
            if current[1] == 0:
                added, removed = sum_diffstats(filediffstats[sha])
                if len(filediffstats[sha]) == 1:
                    currentfilename, = filediffstats[sha].keys()
                    filedesc = f"1 file: {currentfilename}"
                else:
                    filedesc = f'{len(filediffstats[sha])} files'
                blamedesc = f'{indent} {added} lines added, {removed} lines removed in {filedesc}'
                removestats = collections.Counter(
                    commit_lines_remove[sha][file][line]
                    for file in commit_lines_remove[sha]
                    for line in commit_lines_remove[sha][file]
                )
            else:
                currentfilename, (added, removed) = list(filediffstats[sha].items())[
                    current[1] - 1
                ]
                blamedesc = f'{indent} {added} lines added, {removed} lines removed in {currentfilename}'
                removestats = collections.Counter(
                    commit_lines_remove[sha][currentfilename][line]
                    for line in commit_lines_remove[sha][currentfilename]
                )
            if not removestats and not added:
                removedesc = f'{indent} No lines added'
            elif not removestats:
                removedesc = f"{indent} No interesting lines added"
            else:
                maxremove = max(removestats.keys(), key=lambda k: removestats[k])
                totalremove = sum(removestats.values())
                if removestats[maxremove] == totalremove:
                    removepercent = "All lines"
                elif totalremove > 200:
                    removepercent = f'{removestats[maxremove]/totalremove:.1%} of lines'
                else:
                    removepercent = f'{removestats[maxremove]} of {totalremove} lines'
                if maxremove is None:
                    removedesc = f'{indent} {removepercent} are still alive'
                else:
                    try:
                        removecommit = commits[maxremove]
                    except KeyError:
                        ms.set_line(f'git log -1 {maxremove}')
                        removecommit = commits[maxremove] = git_get_commit(maxremove)
                        ms.set_line("")
                    removecommit = commits[maxremove]
                    removedesc = f'{indent} {removepercent} are removed in commit {maxremove[:shalen]} {removecommit["subject"]}'
            ms.set_window(lines + [commitline, blamedesc, removedesc])
            s = read_one_keystroke(timeout=None)
            if s in ("CTRL-D", "CTRL-C"):
                break
            if s == "uparrow":
                current = max(0, current[0] - 1), 0
            elif s == "downarrow":
                current = min(len(objects) - 1, current[0] + 1), 0
            elif s == "pageup":
                current = max(0, current[0] - commitlistheight), 0
            elif s == "pagedown":
                current = min(len(objects) - 1, current[0] + commitlistheight), 0
            elif s == "home":
                current = 0, 0
            elif s == "end":
                current = len(objects) - 1, 0
            elif s == "leftarrow":
                current = current[0], max(0, current[1] - 1)
            elif s == "rightarrow":
                current = current[0], min(len(filediffstats[sha]), current[1] + 1)


if __name__ == "__main__":
    main()
