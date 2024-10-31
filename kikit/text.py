import datetime as dt
import subprocess
from string import Template
from typing import Callable, Optional, Dict, Any
from pcbnewTransition import pcbnew


class Formatter:
    """
    Turns a function into a formatter. Caches the result.
    """
    def __init__(self, fn: Callable[[], str], vars: Dict[str, str]={}) -> None:
        self.fn = fn
        self.value: Optional[str] = None
        self.vars = vars

    def __str__(self) -> str:
        if self.value is None:
            self.value = self.expandVariables(self.fn())
        return self.value

    def expandVariables(self, string: str) -> str:
        try:
            return Template(string).substitute(self.vars)
        except KeyError as e:
            raise RuntimeError(f"Requested text '{string}' expects project variable '{e}' which is missing") from None

def kikitTextVars(board: pcbnew.BOARD, vars: Dict[str, str]={}) -> Dict[str, Any]:

    def command(cmd) -> str:
        res = subprocess.check_output(cmd)
        return res.decode("utf-8").strip()

    def gitDescribeBoard() -> str:
        try:
            # TODO: Maybe this should check the entire directory?
            file_path = board.GetFileName()
            # First get the latest git tag affecting our board file
            commit_hash = command(
                ["git", "log", "-1", "--pretty=format:%H", "--", file_path]
            )

            # We need to generate the dirty flag manually, since
            # git describe does not support --dirty=-d if a hash is specified
            has_unstaged_changes = subprocess.call(
                ["git", "diff", "--quiet", "--", file_path]
            )
            has_staged_changes = subprocess.call(
                ["git", "diff", "--cached", "--quiet", "--", file_path]
            )
            is_dirty = has_unstaged_changes or has_staged_changes

            # Next, use describe on this commit has to generate the resulting string
            described_hash = command(["git", "describe", "--always", commit_hash])

            if is_dirty:
                described_hash += "-d"

            return described_hash
        except subprocess.CalledProcessError:
            return "unknown"

    def gitDateBoard() -> str:
        try:
            file_path = board.GetFileName()
            return command(
                ["git", "log", "-1", "--pretty=format:%cs", "--", file_path]
            )
        except subprocess.CalledProcessError:
            return "unknown"

    availableVars: Dict[str, Formatter] = {
        "date": Formatter(lambda: dt.datetime.today().strftime("%Y-%m-%d"), vars),
        "time24": Formatter(lambda: dt.datetime.today().strftime("%H:%M"), vars),
        "year": Formatter(lambda: dt.datetime.today().strftime("%Y"), vars),
        "month": Formatter(lambda: dt.datetime.today().strftime("%m"), vars),
        "day": Formatter(lambda: dt.datetime.today().strftime("%d"), vars),
        "hour": Formatter(lambda: dt.datetime.today().strftime("%H"), vars),
        "minute": Formatter(lambda: dt.datetime.today().strftime("%M"), vars),
        "second": Formatter(lambda: dt.datetime.today().strftime("%S"), vars),
        "boardTitle": Formatter(lambda: board.GetTitleBlock().GetTitle(), vars),
        "boardDate": Formatter(lambda: board.GetTitleBlock().GetDate(), vars),
        "boardRevision": Formatter(lambda: board.GetTitleBlock().GetRevision(), vars),
        "boardCompany": Formatter(lambda: board.GetTitleBlock().GetCompany(), vars),
        "gitCommit": Formatter(gitDescribeBoard, vars),
        "gitDate": Formatter(gitDateBoard, vars),
    }

    for i in range(10):
        availableVars[f"boardComment{i + 1}"] = Formatter(lambda x = i: board.GetTitleBlock().GetComment(x), vars)

    for var, value in vars.items():
        availableVars[f"user-{var}"] = value

    return availableVars
