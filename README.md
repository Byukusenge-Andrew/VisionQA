# 🎯 Visual QA Sniper

> **Autonomous web UI testing agent powered by Gemini Vision.**  
> No DOM selectors. No fragile CSS class dependencies. Just pure computer vision.

**Gemini Live Agent Challenge — UI Navigator ☸️ Category**

---

## What It Does

Visual QA Sniper is an autonomous QA platform that navigates real web applications **exactly like a human tester** — by looking at the screen. You give it a URL and a plain-English goal, and the agent:

1. Opens a headless browser and takes a screenshot
2. Sends the screenshot to **Gemini 2.0 Flash** for visual analysis
3. Decides which UI element to interact with and calls the appropriate tool
4. Executes the action (click, type, scroll, hover) and captures the new state
5. Detects and reports visual bugs (overlapping text, broken images, contrast failures, misaligned elements)
6. Repeats the action-observation loop until the goal is complete

---

## Features

| Feature | Detail |
|---|---|
| 🧠 **Gemini-powered vision** | Agent sees and understands the UI the way a human does |
| 🔄 **Full action repertoire** | Navigate, click, type, scroll, hover, keyboard shortcuts, back |
| 🐛 **Visual bug detection** | Severity-rated bug reports (critical / high / medium / low) |
| 💾 **Session memory** | Firestore persists all steps, bugs, and screenshots per session |
| 🎯 **Deterministic coords** | 1280×720 locked viewport for reproducible X/Y mappings |
| 🌐 **Premium dashboard** | Real-time dark-mode UI with live browser feed and bug panel |
| ☁️ **Cloud-native** | Deployed on Google Cloud Run via Terraform IaC |

---

## Tech Stack

| Layer | Technology |
|---|---|
| AI Model | Gemini 2.0 Flash via Google ADK |
| Agent Framework | Google Agent Development Kit (ADK) |
| Browser Automation | Playwright (Chromium, headless) |
| Backend | Python 3.12, FastAPI, WebSocket streaming |
| Session Memory | Google Cloud Firestore |
| Infrastructure | Google Cloud Run, Terraform |
| Frontend | Vanilla HTML/CSS/JS (dark glassmorphism) |

---

## Architecture

```
User (Browser)
    │
    ▼
[Dashboard — static/index.html]
    │  WebSocket /ws/stream
    ▼
[FastAPI Backend — main.py]
    │
    ├─► BrowserEngine (Playwright)
    │     Navigate → Screenshot → Click → Screenshot …
    │
    ├─► ADK Agent + Gemini 2.0 Flash
    │     Analyze screenshot → Pick tool → Return action
    │
    └─► SessionManager (Firestore)
          Persist steps, bugs, metadata
```

---

## Local Setup

### Prerequisites
- Python 3.10+
- A Gemini API key from [https://aistudio.google.com](https://aistudio.google.com)

### 1. Clone and enter the project

```bash
git clone https://github.com/YOUR_USERNAME/visual-qa-sniper
cd visual-qa-sniper
```

### 2. Create a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env and set GOOGLE_API_KEY=your_key_here
```

### 5. Start the server

```bash
uvicorn main:app --reload --port 8080
```

### 6. Open the dashboard

Navigate to [http://localhost:8080](http://localhost:8080) in your browser.

---

## Google Cloud Deployment

### Prerequisites
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed and authenticated (`gcloud auth login`)
- [Terraform](https://developer.hashicorp.com/terraform/downloads) installed
- Docker installed

### One-command deploy

```bash
export GOOGLE_API_KEY=your_gemini_api_key
bash deploy.sh YOUR_GCP_PROJECT_ID us-central1
```

This script will:
1. Build and push the Docker image to Artifact Registry
2. Apply Terraform to provision Firestore + Cloud Run
3. Output the live backend URL

---

## Devpost Submission Checklist

| Item | Status |
|---|---|
| Public code repo with this README | ✅ |
| GCP deployment via `deploy.sh` + Terraform | ✅ |
| Architecture diagram | See diagram above |
| Demo video | Record using the live dashboard |
| IaC bonus (Terraform) | ✅ `terraform/` directory |

---

## License

MIT
