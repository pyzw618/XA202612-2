import io

from memoryhub_cli import cli


class FakeClient:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def system_status(self):
        return {"status": "ok", "memory_count": 2}


def test_cli_json_output(monkeypatch):
    monkeypatch.setattr(cli, "MemoryHubClient", FakeClient)
    stdout, stderr = io.StringIO(), io.StringIO()
    assert cli.run(["--json", "status"], stdout=stdout, stderr=stderr) == 0
    assert '"status":"ok"' in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_forget_requires_confirmation(monkeypatch):
    monkeypatch.setattr(cli, "MemoryHubClient", FakeClient)
    stdout, stderr = io.StringIO(), io.StringIO()
    assert cli.run(["forget", "old preference"], stdout=stdout, stderr=stderr) == 2
    assert "confirmation_required" in stderr.getvalue()

