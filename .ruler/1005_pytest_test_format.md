# Pytest test format

Concrete test conventions for Python. The language-agnostic discipline (red/green cycle, real-data-over-mocks, when-TDD-doesn't-apply) lives in `1002_tdd_red_green.md`; this file makes it concrete for pytest.

## Test framework

Use **pytest**. Not `unittest.TestCase`. Invoke via `uv run pytest` (per `1004_uv_package_management.md`).

For notebook (nbdev) test cells see `10_nbdev_any/2002_*` — different conventions there.

## File naming and location

- One test file per module: `test_{module}.py` next to or under a `tests/` directory mirroring `src/`.
- Test functions are prefixed `test_` (pytest auto-discovers).

## Test name expresses what is tested

Read the name aloud as a sentence. It should describe the *behaviour* and the *condition*:

```
test_is_tag_core_repo_true_when_pyproject_lists_tag_core
test_discover_repos_recursive_finds_nested_git_repos
test_sync_removes_orphan_when_file_is_no_longer_in_distribution
```

Pattern: `test_{subject}_{expected_outcome}_when_{condition}`. Avoid vague names like `test_predicate` or `test_basic`.

## Given / When / Then inside each test

Three blocks separated by blank lines and `# Given` / `# When` / `# Then` comments. Makes intent scannable without reading the assertions:

```python
def test_is_tag_core_repo_true_when_pyproject_lists_tag_core(make_repo):
    # Given a repo whose pyproject.toml declares tag-core as a dependency
    repo = make_repo(pyproject='dependencies = ["tag-core>=0.1"]')

    # When we check whether it's a tag-core repo
    result = is_tag_core_repo(repo)

    # Then the predicate returns True
    assert result is True
```

## Shared setup → pytest fixtures (factory pattern preferred)

When several tests need similar test-data, write a **factory fixture** that builds the data with parameters — not a single static fixture. The factory keeps each test's setup visible at the call site:

```python
@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[..., Path]:
    "Factory: build a fake repo under tmp_path with optional pyproject.toml and subdirs."
    counter = {"n": 0}
    def _build(pyproject: str = "", subdirs: Iterable[str] = ()) -> Path:
        counter["n"] += 1
        repo = tmp_path / f"repo{counter['n']}"
        repo.mkdir()
        if pyproject: (repo / "pyproject.toml").write_text(pyproject)
        for sub in subdirs: (repo / sub).mkdir(parents=True)
        return repo
    return _build
```

Each test then reads at a glance: "Given a repo with X, When Y, Then Z." No hidden state.

## One assertion per concept

Multiple `assert` lines are fine if they verify one behaviour. If a test verifies two unrelated behaviours, split it into two tests.

## Self-contained, deterministic, ordering-independent

- Use `tmp_path` (or other pytest-managed fixtures) for any filesystem state. Never write to a path the test does not own.
- No reliance on test execution order. `pytest -p no:randomly` and `pytest --random-order` should both pass.

## Real data over mocks — pytest specifics

Follow the philosophy in `1002_tdd_red_green.md`. In pytest that means:

- File operations — use `tmp_path` and let pytest clean up.
- Database operations — use in-memory SQLite or `tmp_path` for real file-backed dbs.
- Time-dependent behaviour — use `freezegun` or inject the clock.
- External boundaries — patch with `monkeypatch` at the boundary only.

### Example: real filesystem, no mocks needed

```python
def test_load_config_returns_parsed_dict_when_file_is_valid_json(tmp_path):
    # Given a config file containing valid JSON
    config = tmp_path / "config.json"
    config.write_text('{"name": "foo", "size": 42}')

    # When we load it
    result = load_config(config)

    # Then the parsed dict matches the file content
    assert result == {"name": "foo", "size": 42}
```

### Example: mock only the external boundary

```python
def test_fetch_user_returns_cached_when_network_unreachable(tmp_path, monkeypatch):
    # Given a cache file with a known user and a network that always fails
    cache = tmp_path / "users.json"
    cache.write_text('{"alice": {"id": 1}}')
    monkeypatch.setattr("requests.get", lambda *a, **kw: (_ for _ in ()).throw(ConnectionError()))

    # When we fetch "alice"
    user = fetch_user("alice", cache_path=cache)

    # Then the cached value is returned (no exception, no real network call)
    assert user == {"id": 1}
```
