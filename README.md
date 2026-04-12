# redpaper

AI wallpaper generator for Windows. Every morning, Claude writes a ComfyUI image prompt tailored to each virtual desktop's theme, generates the image, and sets it as the wallpaper — per monitor, per desktop.

## How it works

1. A scheduler fires at a configurable time each day (default: 8 AM)
2. For each virtual desktop, **Claude CLI** (`claude -p`) generates a fresh ComfyUI prompt based on the desktop's theme
3. The prompt is submitted to a local **ComfyUI** instance
4. The generated image is saved and set as the wallpaper on the correct monitors
5. When you switch virtual desktops, redpaper detects the switch and re-applies the right wallpaper automatically

A web UI is served locally for managing desktop themes, viewing history, and triggering manual generations.

## Prerequisites

| Requirement | Notes |
|---|---|
| Windows 10/11 | Virtual desktop support required |
| Python 3.11+ | |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | Must be running locally |
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) | `npm install -g @anthropic-ai/claude-code`, then `claude login` |
| A diffusion model | Tested with `z_image_turbo_bf16`; workflow node IDs are configurable |

## Installation

### 1. Clone and install dependencies

```bash
git clone https://github.com/rblaurent/redpaper.git
cd redpaper
pip install -r requirements.txt
```

### 2. Configure

Edit `config.json`:

```json
{
  "web_port": 18080,
  "schedule_cron": "0 8 * * *",
  "claude_path": "C:/path/to/claude.cmd",
  "comfyui_port": 8188,
  "output_dir": "C:/path/to/redpaper/output",
  "seed_node_id": "31"
}
```

| Key | Description |
|---|---|
| `web_port` | Port for the web UI |
| `schedule_cron` | Cron expression for daily generation |
| `claude_path` | Full path to `claude.cmd` (find it with `where claude`) |
| `comfyui_port` | ComfyUI API port |
| `output_dir` | Where generated wallpapers are saved |
| `seed_node_id` | ComfyUI workflow node ID for the seed (for randomisation) |

### Workflow setup

redpaper injects the AI-generated prompt into your ComfyUI workflow via a `{{prompt}}` placeholder. Open `workflow.json` and replace the text content of your positive prompt node with `{{prompt}}`. The seed node ID tells redpaper which node to randomise on each run — find it by checking node numbers in ComfyUI's web UI.

### 3. Install as a Windows Service (recommended)

This installs redpaper as a Windows service that starts automatically on boot.

**Run as Administrator:**

```
install_service.bat
```

Or manually:

```
python service.py install
net start redpaper
```

The web UI will be available at `http://127.0.0.1:18080`.

### Service management

```bash
net start redpaper      # start
net stop redpaper       # stop
python service.py remove  # uninstall
```

### 4. Running without a service (manual / dev)

```bash
python main.py
```

## Usage

Open `http://127.0.0.1:18080` in your browser.

- **Desktops** — each Windows virtual desktop is listed; set a theme describing the visual world you want
- **Generate now** — trigger an immediate generation without waiting for the schedule
- **History** — browse previously generated wallpapers and apply any of them manually
- **Settings** — adjust the schedule, ComfyUI port, and Claude path

## Catchup generation

If ComfyUI wasn't running at the scheduled time, redpaper polls every 5 minutes. As soon as ComfyUI comes online, it will generate the day's wallpaper automatically.

## Troubleshooting

**Claude not found**
Run `where claude` in a terminal to get the full path, then set `claude_path` in `config.json`. Make sure you've run `claude login` at least once.

**No wallpaper generated**
Check that ComfyUI is running and reachable at the configured port. The web UI shows ComfyUI status on the main page.

**Service fails to start**
Make sure you ran the install as Administrator. Check Windows Event Viewer → Windows Logs → Application for `redpaper` entries.

**Wrong node IDs**
Open your workflow in ComfyUI's web UI. Each node has a number in its title bar — use those for `positive_prompt_node_id`, `negative_prompt_node_id`, and `seed_node_id`.
