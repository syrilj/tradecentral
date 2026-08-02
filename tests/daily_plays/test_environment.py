from edge.daily_plays.config import load_project_environment


def test_project_environment_loads_key_without_overwriting_shell(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("LSE_API_KEY=file-key\n", encoding="utf-8")

    monkeypatch.delenv("LSE_API_KEY", raising=False)
    load_project_environment([env_path])
    assert __import__("os").environ["LSE_API_KEY"] == "file-key"

    monkeypatch.setenv("LSE_API_KEY", "shell-key")
    load_project_environment([env_path])
    assert __import__("os").environ["LSE_API_KEY"] == "shell-key"


def test_project_environment_can_be_disabled(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("LSE_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    monkeypatch.setenv("DAILY_PLAYS_DISABLE_DOTENV", "1")

    load_project_environment([env_path])

    assert "LSE_API_KEY" not in __import__("os").environ
