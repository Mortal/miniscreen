import argparse
import collections
import datetime
import subprocess
from typing import TypedDict

from miniscreen import MiniScreen, read_one_keystroke
from miniscreen.minifutures import next_keystroke, check_output, create_task, run_coroutine


parser = argparse.ArgumentParser()
parser.add_argument("revision_range")

git_executable = "/usr/bin/git"


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


async def git_cat_file(sha: str) -> tuple[str, bytes]:
    d = await check_output((git_executable, "cat-file", "--batch"), input=sha.encode())
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


async def git_get_commit(sha: str) -> Commit:
    type, data = await git_cat_file(sha)
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


async def sha_has_filename(sha: str, filename: str) -> bool:
    try:
        await check_output(
            (git_executable, "rev-parse", "--quiet", "--verify", f"{sha}:{filename}")
        )
    except subprocess.CalledProcessError:
        return False
    return True


async def git_show_numstat(sha: str) -> dict[str, DiffStat]:
    numstat = await check_output(
        (git_executable, "show", "--format=", "--numstat", sha),
    )
    filediffstat: dict[str, DiffStat] = {}
    if not numstat.strip(b"\n"):
        return filediffstat
    for line in numstat.strip(b"\n").split(b"\n"):
        assert line.count(b"\t") >= 2
        added, removed, filename = line.decode().split("\t", 2)
        filediffstat[filename] = (int(added), int(removed))
    return filediffstat


async def git_blame(sha: str, filename: str) -> list[tuple[LineSource, bytes]]:
    if not (await sha_has_filename(sha, filename)):
        return []
    blame_b = await check_output(
        (git_executable, "blame", "--porcelain", sha, "--", filename),
    )
    if not blame_b.strip(b"\n"):
        return []
    blame_output_lines = iter(blame_b.strip(b"\n").split(b"\n"))
    lines: list[tuple[LineSource, bytes]] = []
    linedata_for_sha: dict[bytes, dict[bytes, bytes | None]] = {}
    for lineno, headerline in enumerate(blame_output_lines, 1):
        assert headerline.count(b" ") >= 2, headerline
        blamesha, blameline, finalline, *_ignore = headerline.split(b" ", 3)
        linedata: dict[bytes, bytes | None] = {}
        for extraline in blame_output_lines:
            if extraline.startswith(b"\t"):
                contents = extraline[1:] + b"\n"
                break
            k_b, sep_b, v_b = extraline.partition(b" ")
            if sep_b:
                linedata[k_b] = v_b
            else:
                linedata[k_b] = None
        else:
            raise Exception("Unexpected EOF in git blame")
        if b"filename" in linedata:
            blamefile = linedata[b"filename"]
            assert blamefile is not None
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
            assert blamefile is not None
        lines.append(((blamesha.decode(), blamefile.decode(), int(blameline)), contents))
    return lines


def sum_diffstats(filediffstat: dict[str, DiffStat]) -> DiffStat:
    totaladded = 0
    totalremoved = 0
    for filename, (added, removed) in filediffstat.items():
        totaladded += added
        totalremoved += removed
    return totaladded, totalremoved


def main() -> None:
    args = parser.parse_args()
    run_coroutine(async_main(args.revision_range))


async def async_main(revision_range: str) -> None:
    objects: list[str] = []
    filediffstats: dict[str, dict[str, DiffStat]] = {}
    file_to_commits: dict[str, list[str]] = {}
    # [sha1][file][sha2] is a set of line numbers of sha1:file
    # that are present in sha2
    commit_commit_lines: dict[str, dict[str, dict[str, set[int]]]] = {}
    # [sha1][file][line] is the sha2 that removes the line
    commit_lines_remove: dict[str, dict[str, dict[int, str | None]]] = {}
    # [sha1][file] is the list of sha2 that the deleted lines are added in
    commit_lines_removed: dict[str, dict[str, list[str]]] = {}
    commitlistheight = 30
    commits: dict[str, Commit] = {}
    file_blames: dict[str, list[tuple[str, list[tuple[LineSource, bytes]]]]] = {}
    current = len(objects) - 1, 0
    shalen = 10
    with MiniScreen() as ms:

        screen_dirty = True

        def maybe_rerender() -> None:
            nonlocal screen_dirty
            if screen_dirty:
                render()

        def render():
            nonlocal screen_dirty

            if not objects:
                screen_dirty = True
                return

            screen_dirty = False
            lines = []
            for i in range(commitlistheight):
                object_index = current[0] - commitlistheight + 1 + i
                if object_index < 0:
                    lines.append("")
                    continue
                sha = objects[object_index]
                star = "*" if object_index == current[0] else " "
                if sha in commits:
                    c = commits[sha]
                    lines.append(f'{star} {sha[:shalen]} {c["subject"]}')
                else:
                    screen_dirty = True
                    lines.append(f'{star} {sha[:shalen]}')

            indent = "  " + " " * shalen
            sha = objects[current[0]]
            try:
                c = commits[sha]
            except KeyError:
                commitline = ""
                blamedesc = ""
                removedesc = f"{indent} Loading commit"
                screen_dirty = True
                ms.set_window(lines + [commitline, blamedesc, "", removedesc])
                return
            commitline = f'{indent} {c["author_name"]} {c["author_date"]}'
            blamedesc = ""
            removedesc = f"{indent} Loading blame"
            if sha not in filediffstats:
                ms.set_window(lines + [commitline, blamedesc, "", removedesc])
                screen_dirty = True
                return
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
                removedstats = collections.Counter(
                    sha2
                    for file in commit_lines_removed[sha]
                    for sha2 in commit_lines_removed[sha][file]
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
                removedstats = collections.Counter(
                    sha2
                    for sha2 in commit_lines_removed[sha].get(currentfilename, [])
                )
            if not removedstats and not removed:
                removeddesc = f'{indent} No lines deleted'
            elif not removedstats:
                removeddesc = f"{indent} No interesting lines deleted from this patchset"
            else:
                maxremoved = max(removedstats.keys(), key=lambda k: removedstats[k])
                totalremove = sum(removedstats.values())
                if removedstats[maxremoved] == totalremove:
                    pct = "All lines"
                elif totalremove > 200:
                    pct = f'{removedstats[maxremoved]/totalremove:.1%} of lines'
                else:
                    pct = f'{removedstats[maxremoved]} of {totalremove} lines'
                assert maxremoved is not None
                removeddesc = f'{indent} {pct} removed are from commit {maxremoved[:shalen]}'
                try:
                    removedcommit = commits[maxremoved]
                except KeyError:
                    if maxremoved in objects:
                        screen_dirty = True
                    else:
                        removeddesc = f'{indent} {pct} removed are from an old commit ({maxremoved[:shalen]})'
                else:
                    removeddesc += f' {removedcommit["subject"]}'
            if not removestats and not added:
                removedesc = f'{indent} No lines added'
            elif not removestats:
                removedesc = f"{indent} No interesting lines added"
            else:
                maxremove = max(removestats.keys(), key=lambda k: (k is not None, removestats[k]))
                totalremove = sum(removestats.values())
                if removestats[maxremove] == totalremove:
                    pct = "All lines"
                elif totalremove > 200:
                    pct = f'{removestats[maxremove]/totalremove:.1%} of lines'
                else:
                    pct = f'{removestats[maxremove]} of {totalremove} lines'
                if maxremove is None:
                    removedesc = f'{indent} {pct} are still alive'
                else:
                    removedesc = f'{indent} {pct} are removed in commit {maxremove[:shalen]}'
                    try:
                        removecommit = commits[maxremove]
                    except KeyError:
                        screen_dirty = True
                    else:
                        removedesc += f' {removecommit["subject"]}'
            ms.set_window(lines + [commitline, blamedesc, removedesc, removeddesc])

        exiting = False

        async def loader() -> None:
            nonlocal screen_dirty, current

            rev_list_output = await check_output(
                (git_executable, "rev-list", "--stdin"),
                input=revision_range.encode(),
            )
            objects[:] = rev_list_output.decode().split()[::-1]
            for o in objects:
                commit_commit_lines[o] = {}
                commit_lines_remove[o] = {}
                commit_lines_removed[o] = {}
            current = len(objects) - 1, 0
            maybe_rerender()
            if exiting:
                return
            while len(commits) < len(objects):
                maybe_rerender()
                if exiting:
                    return
                nextsha = objects[-1 - len(commits)]
                ms.set_line(f'git log -1 {nextsha}')
                commits[nextsha] = await git_get_commit(nextsha)
                ms.set_line("")
            while len(filediffstats) < len(objects):
                maybe_rerender()
                if exiting:
                    return
                nextsha = objects[-1 - len(filediffstats)]
                ms.set_line(f'git show --numstat {nextsha}')
                filediffstats[nextsha] = await git_show_numstat(nextsha)
                for filename in filediffstats[nextsha]:
                    ms.set_line(f'git blame {nextsha} -- {filename}')
                    blame_lines = await git_blame(nextsha, filename)
                    if filename in file_blames:
                        prevsha, prev_blame_lines = file_blames[filename][-1]
                        for line_source, contents in sorted(set(blame_lines) - set(prev_blame_lines)):
                            # Skip if line only contains delimiters and whitespace
                            if not contents.strip(b" \t\n\r<>(){}[],;"):
                                continue
                            blamesha, blamefile, blameline = line_source
                            if prevsha == objects[current[0]]:
                                screen_dirty = True
                            commit_lines_removed[prevsha].setdefault(
                                blamefile, []
                            ).append(blamesha)

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
            maybe_rerender()

        loader_task = create_task(loader())

        while True:
            maybe_rerender()
            s = await next_keystroke()
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
                current = current[0], min(len(filediffstats[objects[current[0]]]), current[1] + 1)
            else:
                continue
            screen_dirty = True
        exiting = True
        await loader_task


if __name__ == "__main__":
    main()
