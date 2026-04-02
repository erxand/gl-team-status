# GL Team Status

Interactive TUI for monitoring team MR review status on GitLab.

## Prerequisites

- Python 3.10+
- [glab CLI](https://gitlab.com/gitlab-org/cli) installed and authenticated (`glab auth login`)
- Run from a directory that is a GitLab-backed git repository

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
chmod +x main.py
```

### Alias

```bash
mkdir -p ~/.local/bin
ln -s $(pwd)/main.py ~/.local/bin/gls
```

Then run `gls` from any GitLab repo directory.

## Usage

On first launch, the settings view opens automatically. Select team members to follow, then press `s` to switch to the MR list.

### Hotkeys

| Key | Action |
|-----|--------|
| `q` | Quit |
| `s` | Toggle settings view |
| `o` | Open MR in browser |
| `f` | Force refresh |
| `j`/`k` | Cursor down/up |
| `/` | Search / filter |
| `Enter` | Toggle follow (settings view) |

### Columns

- **MR** — merge request ID (`!123`)
- **Author** — `@username`
- **Title** — MR title (fuzzy-highlighted when searching)
- **Approvals** — `approved/required` (e.g. `1/2`)
- **Threads** — total unresolved threads, with AI count in parentheses (e.g. `4 (1 AI)`)
- **Pipeline** — latest pipeline status
