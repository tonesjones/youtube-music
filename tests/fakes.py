"""Fake YouTube Music client shared by the sync-apply and suggest tests."""


class NoThrottle:
    def __init__(self):
        self.waits = 0

    def wait(self):
        self.waits += 1


class FakeYT:
    """Records every call; add returns setVideoId 'new<N>'. Write number `fail_on` fails."""

    def __init__(self, playlists=None, search_results=None, fail_on=None):
        self.playlists = playlists or {}
        self.search_results = search_results or {}  # query -> results
        self.fail_on = fail_on
        self.calls = []
        self.n = 0

    def get_playlist(self, pid, limit=None):
        self.calls.append(("get_playlist", pid))
        return {"tracks": self.playlists.get(pid, [])}

    def get_history(self):
        self.calls.append(("get_history",))
        return []

    def search(self, query, filter=None):
        self.calls.append(("search", query))
        return self.search_results.get(query, [])

    def _write(self, name, args, response):
        self.calls.append((name, *args))
        self.n += 1
        return {"error": "boom"} if self.fail_on == self.n else response

    def add_playlist_items(self, pid, ids, duplicates=False):
        ok = {"status": "STATUS_SUCCEEDED", "playlistEditResults": [{"setVideoId": f"new{self.n + 1}"}]}
        return self._write("add", (pid, ids[0]), ok)

    def edit_playlist(self, pid, moveItem=None):
        return self._write("move", (pid, *moveItem), "STATUS_SUCCEEDED")

    def remove_playlist_items(self, pid, videos):
        return self._write("remove", (pid, videos[0]["videoId"], videos[0]["setVideoId"]), "STATUS_SUCCEEDED")

    def writes(self):
        return [c for c in self.calls if c[0] in ("add", "move", "remove")]
