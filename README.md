<div align="center">

# 🤖 Jarvis AI Desktop Agent

**A self-hosted, autonomous AI agent for Linux — it plans, executes, and gets real work done.**

[![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?logo=apache)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.0.0-orange)](https://github.com/dev-core-busy/jarvis/releases)
[![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey?logo=linux)](https://www.linux.org/)
[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-brightgreen)](https://github.com/dev-core-busy/jarvis/pulls)
[![OpenClaw Compatible](https://img.shields.io/badge/OpenClaw-Compatible-6366f1)](https://github.com/dev-core-busy/jarvis#openclaw-skill-ecosystem)

*Control your Linux desktop with natural language. Receive tasks via WhatsApp. Search your knowledge base. Automate everything.*

[**Live Demo**](https://jarvis-ai.info) · [**Report Bug**](https://github.com/dev-core-busy/jarvis/issues) · [**Request Feature**](https://github.com/dev-core-busy/jarvis/issues) · [**Contribute**](#contributing)

---

![Jarvis portal — role-based hub for chat, support and admin tools](docs/screenshots/portal.png)

</div>

---

## 📋 Table of Contents

- [Overview](#overview)
- [Screenshots](#screenshots)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Installation](#installation)
- [Configuration](#configuration)
- [Multi-User Chat](#multi-user-chat)
- [Multi-Agent System](#multi-agent-system)
- [Skill System](#skill-system)
- [Email Automation & Outlook Add-in](#email-automation--outlook-add-in)
- [SAP Analysis Area](#sap-analysis-area)
- [Short Tracks](#short-tracks)
- [WhatsApp Integration](#whatsapp-integration)
- [Knowledge Base](#knowledge-base)
- [Vision & Face Recognition](#vision--face-recognition)
- [AD/LDAP & Security](#adldap--security)
- [Multimedia Attachments](#multimedia-attachments)
- [Feedback & Self-Improvement](#feedback--self-improvement)
- [Cognitive Evolution](#cognitive-evolution)
- [Client Apps](#client-apps)
- [API Reference](#api-reference)
- [Contributing](#contributing)
- [Third-Party Licenses](#third-party-licenses)
- [License](#license)

---

## Overview

Jarvis is a **self-hosted, autonomous AI agent** that runs on a Linux server. Give it a goal in plain language — through the web chat, the built-in **Support portal**, a **task pane inside Outlook or Excel**, or even **WhatsApp** — and it plans and executes: browsing the web, reading and writing files, running code, editing existing spreadsheets, generating Office documents & diagrams, answering email by rule, evaluating SAP data read-only, managing your calendar. Whenever you want, you can watch it work live on the desktop via an **optional VNC view**.

```
"Find all emails from last week about Project Alpha, summarize them,
 and create a calendar event for the follow-up meeting."
```

Jarvis handles it — and because it's **multi-LLM**, **multi-user**, and wrapped in a real **security layer with sandboxed execution**, you can safely open it to a whole team.

---

## Screenshots

<div align="center">

**Interactive API console** — every REST endpoint listed, explained, with a live test caller (admin-only, `/api`):

![Interactive API console](docs/screenshots/api_console.png)

**Security settings** — attack prevention, sandbox status & incident log under Settings → Security:

![Security settings](docs/screenshots/security.png)

</div>

---

## Key Features

### 🖥️ Real Desktop Control (live VNC view)
Jarvis drives a real Linux desktop — launching apps, clicking, typing. Toggle the **live desktop view (noVNC)** to watch or take over at any time; screenshots feed straight back into the LLM context, so the agent sees what it's doing. No blind automation.

### 🔀 Multi-LLM Support
Switch between AI providers without restarting anything:
- **Google Gemini** (gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-pro, …)
- **Anthropic Claude** (claude-opus-4, claude-sonnet-4-5, claude-haiku-4, …)
- **OpenRouter** (hundreds of models via one API)
- **Local Ollama** (llama3, mistral, qwen2.5, … — fully offline)
- Any **OpenAI-compatible** endpoint

Both native tool/function calling **and** prompt-based tool calling are supported — so even models without native tool support can use all of Jarvis's capabilities.

### 🤖 Multi-Agent System & Role Delegation
The **main agent can spawn autonomous sub-agents** for parallel or background tasks. Each sub-agent runs independently, reports back in real-time, and appears in the sidebar. Complex multi-step workflows run in parallel without blocking the main conversation.

On top of that, an admin can define **named role agents** — each with its own system prompt, tool subset, LLM profile, reasoning depth and step limit. The main agent gets a single `delegate(role, task)` tool, hands off a sub-task, **waits**, and continues with the result. A role can only ever *narrow* the caller's permissions, never widen them.

### 💬 Multi-User Chat
A built-in **user-to-user chat** (`/userchat`) lets all logged-in users communicate in real-time — with image galleries, audio/video players, file attachments, lightbox preview, and a forward/save context menu.

### 📎 Multimedia Attachments
Send **images, audio, video, and PDFs** directly in the Jarvis chat:
- Images are sent to the LLM for visual analysis (all providers supported)
- Audio/Video is transcribed locally via Whisper before the LLM sees it
- PDFs are extracted and injected as text context
- In-chat gallery with lightbox, right-click context menu, and mobile long-press support

### 📱 WhatsApp Agent
Send Jarvis a voice note or text message on WhatsApp, get a response back. Voice messages are transcribed via faster-whisper (runs locally, no cloud). Perfect for mobile task delegation.

### 📚 Knowledge Base (hybrid RAG)
Drop PDFs, DOCX files, or plain text into watched folders. Jarvis indexes them into a **FAISS** index (`multilingual-e5-small`, 384-dim, cosine) and answers with a **hybrid search**: two semantic channels plus a lexical **BM25** channel, fused by Reciprocal Rank Fusion. Pure embeddings are structurally weak on exact identifiers such as error codes or `@STR_UCASE`; BM25 covers exactly that. Multi-folder support, incremental re-indexing on file changes, crash-safe resume, and a TF-IDF fallback when no vector stack is available.

### 🧩 Modular Skill System
Skills are self-contained Python packages that extend Jarvis with new capabilities. Install, enable, disable, and configure them through the UI without touching config files. Compatible with [OpenClaw](https://github.com/steipete/gogcli) skills.

### 👁️ Vision & Face Recognition
The optional **Vision Skill** adds real-time face recognition via dlib/face_recognition. Define per-person actions (webhook, LLM prompt, log-only) with configurable cooldown and tolerance. Works with USB cameras or IP cameras.

### 🛡️ Security Layer & Sandbox
Built to be opened to a whole team — every restriction is **enforced in code**, not just requested in the prompt (so it can't be talked around, base64-encoded around, or "learned" around):
- **Sandboxed execution** for network/domain users — shell commands run as an unprivileged OS user; file access is confined (no system/root/secret paths, symlink-escape safe)
- **Prompt-injection, jailbreak & Base64-obfuscation detection** across chat, support & WhatsApp (heuristics + LLM classifier)
- **Automatic account lockout** on repeated attack attempts, with a full, itemized violation log
- **A private `/tmp` per user** — all network users share one OS account, so file permissions cannot separate them (0600 would lock out their own run). A bubblewrap mount namespace binds a per-user directory onto `/tmp` instead: another user's files are not unreadable, they are **not present**. `--unshare-pid` hides foreign processes too (measured: 5 visible instead of 288). The model-facing path stays `/tmp/result.xlsx`, so no prompt had to change.
- **Role-based rights** (local admins vs. network users) + sub-agents inherit the caller's confinement — no privilege escalation
- **Time-delayed runs are bound to their owner** — a scheduled job carries the identity of whoever created it, not of whoever chatted last. Channels without an account (WhatsApp, Telegram, the notify API) are *always* unprivileged, and creating scheduled triggers is admin-only

### 🔐 Authentication & Access
- **Active Directory / LDAP** authentication (no domain join required)
- **2FA / TOTP** for all users
- Granular **knowledge-editor permissions** (per user or AD group)
- HTTPS with auto-generated self-signed certificates or Let's Encrypt
- Token-based auth (HMAC-SHA256, 30-day validity)

### 🌐 Google Workspace Integration
Manage Gmail, Google Calendar, and Google Drive through natural language commands — powered by the openclaw/gog CLI.

### 🤖 Browser Automation
Full browser control via CDP (Chrome DevTools Protocol) and xdotool. The agent can navigate websites, fill forms, click elements, and extract information.

### ⭐ Feedback & Self-Improvement
After every bot response, one-click **👍 👎 ❌ feedback** triggers automatic LLM analysis, generates 3–5 better alternatives, and permanently feeds learning rules into the knowledge base — no manual configuration needed.

### 🧬 Cognitive Evolution
The **Cognitive Evolution Skill** lets Jarvis improve and extend itself: it analyzes gaps, proposes new skills or code patches, validates them through a second LLM, and applies them — including hot-reloading its own engine without a service restart.

### 🧭 Role-based Portal, Chat & Support Assistant
A clean `/portal` hub routes each user to what they're allowed to use: the AI **chat**, the **user-to-user chat**, and a dedicated **Support Assistant** (`/support`) that answers from your knowledge base + Jira/Confluence with relevance-ranked sources. Admin tools (settings, VNC, security) appear only for administrators.

### 📄 Office & File Generation
Generate **Word, Excel, PowerPoint and PDF** on the fly (python-docx / openpyxl / python-pptx + LibreOffice) — including diagrams with boxes and connectors. Any generated file (or image) is delivered straight into the chat as an inline preview or a one-click download chip.

### 📊 Knowledge Groups & Bulk Tagging
Organize documents into logical groups (multi-membership), scope searches to a group, and manage everything in a **full-screen tagging matrix** — assign hundreds of documents to groups in seconds.

### 🔌 Interactive API Console
An admin-only, auto-generated **API explorer** at `/api`: every REST endpoint listed, explained, with examples and a **live test caller**. The OpenAPI schema and Swagger/ReDoc are gated behind admin auth.

### 📧 Exchange Email Automation & Outlook Add-in
Connect your in-house **Exchange** (EWS, with IMAP/SMTP as a fallback). Every user stores **their own mailbox** — no service account with impersonation — and writes **their own rules** in plain language. When a new message arrives, the rule's prompt runs and the model picks the action: reply, draft, move, forward, send, delete. Named **reply styles** (tone + signature) can be selected per rule, per preview, or chosen automatically.

An **Outlook web add-in** brings the same area into a task pane in classic Outlook and Outlook on the web: process the selected message with a rule, preview a reply before it goes out, and sign in **without a password** via the Exchange identity token. → [details](#email-automation--outlook-add-in)

### 📊 SAP Analysis Area
A dedicated `/sap` area for management: pick an analysis template, the agent evaluates **read-only** (OData GET, SQL SELECT/WITH, RFC whitelist) and answers with figures and sources. Ships with 24 templates across 6 categories, including segment reporting (IFRS 8), expected credit losses (IFRS 9), consolidation, internal controls, VAT/Intrastat and ESG/CSRD. Each user can store a **personal SAP account**; the admin's account becomes the read-only fallback. Server certificates can be **pinned** instead of switching validation off. → [details](#sap-analysis-area)

### 🎯 Short Tracks
Named **drop zones** with a stored prompt. Drag a file or a URL onto one and it runs — result on the card, generated files as download chips. Admins create global zones, every user creates their own; runs are always unprivileged and limited to an admin-approved set of tool areas. → [details](#short-tracks)

### 📈 Charts & Diagrams
A validated `create_chart` tool builds bar/line/pie/scatter charts **server-side from your data** — it reads CSV/TSV/XLSX itself, aggregates, sorts, and validates before rendering, so the model never has to retype numbers. A theme layer keeps every chart on brand in light and dark mode. **Mermaid** diagrams render inline in chat, loaded on demand.

### 📗 Spreadsheet & Form Intelligence
Existing workbooks are **edited, not rebuilt**: `xlsx_inspect` returns the structure of even a 360,000-cell workbook in a few kilobytes, `xlsx_read_range`, `xlsx_merge` and `xlsx_edit` then transform the real file — formulas, column widths and merged ranges survive. The data never passes through the language model; the model describes the transformation, the backend performs it. `pdf_formular_extrakt` does the same for stacks of filled-in **form PDFs**, mapping values to labels by **geometry** rather than by reading order, with a learned template and OCR when the text layer is damaged.

### 🔄 Knowledge Sync Between Sites
Run several Jarvis instances in one network: an admin shares a knowledge folder at site A, site B **pulls** it (one-way read-sync) and gets it as a local mirror *and* as RAG entries. Incremental via manifest + SHA-256, certificate-pinned TLS, mirror folders are write-protected and marked in the UI.

### 🧠 Reasoning Control
One provider-independent scale — `off | low | medium | high | max` — translated per provider (Gemini thinking budget, OpenAI `reasoning_effort`, OpenRouter `reasoning`, Anthropic `thinking` + `output_config`). Set it globally, per LLM profile, or per single request. If a model rejects the parameter, the request is retried once without it, so the user gets an answer instead of an error.

### 👥 Presence & Audit
An admin-only **"logged-in users"** panel shows who is online, idle, or offline — derived from real human activity (page load, click, keypress), not from background polling. Alongside it: a tool audit log, an itemized access-violation list, per-area telemetry, and full LLM conversation logs with **uncut prompts**, all self-pruning by age.

### 📱 Desktop & Mobile Clients
Use Jarvis anywhere: a **native Windows app** (Go — tray, on-device speech-to-text, animated avatar, auto-update), a **native Android app** (Kotlin/Jetpack Compose — streaming chat, voice, attachments, push), and **iOS** via an installable PWA (native app on the roadmap). All share one login, chat history, and attachments. → [details](#client-apps)

---

## Architecture

```mermaid
flowchart LR
    subgraph Clients["📱 Clients"]
        WebUI["Web UI\n(Browser)"]
        AndroidApp["Android App"]
        WindowsApp["Windows App"]
        WA["WhatsApp"]
    end

    subgraph Backend["⚙️ FastAPI Backend :443"]
        Agent["JarvisAgent\n(agent.py)"]
        AgentMgr["AgentManager\n(Multi-Agent)"]
        SkillsAPI["Skills API"]
        WAProxy["WhatsApp Proxy"]
        SkillMgr["SkillManager"]

        subgraph Tools["🔧 Tool Layer"]
            ToolList["shell · desktop · filesystem · screenshot\nknowledge · memory · browser · whatsapp · vision"]
        end

        LLM["LLM Client\n(Multi-Provider)"]
        VNCServer["x11vnc :5900\n(→ noVNC :6080)"]
        Bridge["Baileys Bridge\nNode.js :3001"]
    end

    WebUI -->|WSS/HTTPS| Agent
    AndroidApp -->|HTTPS| Agent
    WindowsApp -->|HTTPS| Agent
    WA --> Bridge --> WAProxy --> Agent

    Agent --> AgentMgr
    AgentMgr -->|spawns| Agent
    Agent --> SkillMgr --> Tools
    Agent --> LLM
    VNCServer --> WebUI
```

### Component Overview

| Component | File | Description |
|-----------|------|-------------|
| FastAPI Server | `backend/main.py` | HTTP/WebSocket endpoints, auth, AD/LDAP, WhatsApp proxy |
| Agent Loop | `backend/agent.py` | Task execution, tool calling, LLM orchestration, multimodal |
| Agent Manager | `backend/agent.py` | Main + sub-agent lifecycle, parallel execution |
| LLM Client | `backend/llm.py` | Multi-provider abstraction (Gemini, Claude, OpenRouter, Ollama) |
| Config | `backend/config.py` | Environment + settings.json management |
| Skill Manager | `backend/skills/manager.py` | Load, enable, disable, configure skills |
| Tool Base | `backend/tools/base.py` | `BaseTool` class all tools inherit from |
| Learning | `backend/learning.py` | Feedback processing, self-improvement, knowledge indexing |
| WhatsApp Bridge | `services/whatsapp-bridge/index.js` | Baileys v7 + Express API |
| Frontend | `frontend/index.html` + `js/` | Main SPA — agent chat, settings, VNC |
| PWA Chat | `frontend/chat.html` + `js/chat.js` | Lightweight PWA chat with history persistence |
| User Chat | `frontend/userchat.html` + `js/userchat.js` | Multi-user real-time chat with media |

---

## Tech Stack

### Backend
| Technology | Version | Purpose |
|-----------|---------|---------|
| Python | 3.13 | Core runtime |
| FastAPI | latest | REST API + WebSocket server |
| uvicorn | latest | ASGI server |
| ldap3 | latest | Active Directory / LDAP authentication |
| faster-whisper | latest | Voice transcription (CPU, int8) |
| pdfplumber / pypdf | latest | PDF text extraction |
| pytesseract + pdf2image | latest | OCR for scanned or damaged PDFs |
| faiss-cpu | ≥1.7.4 | Vector index (`IndexFlatIP`, cosine) |
| sentence-transformers | <4.0 | Multilingual embeddings (`intfloat/multilingual-e5-small`, 384-dim) |
| python-docx / openpyxl / python-pptx | latest | Office document generation and editing |
| exchangelib | latest | Exchange EWS (email skill; IMAP/SMTP fallback via stdlib) |
| cryptography | latest | Ed25519 license verification, credential encryption (Fernet) |
| mcp | ≥1.5 | Model Context Protocol client (stdio + streamable HTTP) |
| APScheduler | <4.0 | Scheduled jobs |
| face_recognition | latest | Face detection + recognition (dlib) |

### Frontend
| Technology | Purpose |
|-----------|---------|
| Vanilla JS | Zero-dependency UI (no build system) |
| CSS Custom Properties | Dark Glassmorphism theme |
| WebSocket API | Real-time agent communication |
| noVNC | In-browser VNC client |
| Chart.js (+ datalabels, annotation) | Interactive charts, themed light/dark |
| Mermaid | Flow and sequence diagrams, loaded on demand |
| Office.js | Outlook and Excel task-pane add-ins |
| Service Worker | PWA offline support |

### Desktop / System
| Technology | Purpose |
|-----------|---------|
| Xvfb | Virtual framebuffer (headless X11) |
| Openbox | Lightweight window manager |
| x11vnc | VNC server for X11 session |
| websockify | WebSocket-to-TCP proxy (noVNC bridge) |
| xdotool | X11 automation (keyboard, mouse, window management) |
| bubblewrap | Per-user mount/PID namespace for agent shell runs |
| LibreOffice | Headless conversion of Office documents to PDF |

### WhatsApp
| Technology | Purpose |
|-----------|---------|
| Node.js 20+ | WhatsApp bridge runtime |
| Baileys v7 | WhatsApp Web API (no official API required) |
| Express | HTTP API for bridge ↔ backend communication |

---

## Installation

### Prerequisites

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y \
  python3.13 python3.13-venv python3-pip \
  nodejs npm \
  git \
  xvfb x11vnc openbox \
  websockify \
  xdotool \
  ffmpeg \
  cmake libboost-all-dev  # required for face_recognition (dlib)
```

> **Note:** Node.js 20+ is required. Use [nvm](https://github.com/nvm-sh/nvm) if your distro ships an older version.

### Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/dev-core-busy/jarvis.git
cd jarvis

# 2. Create Python virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install WhatsApp bridge dependencies
cd services/whatsapp-bridge
npm install
cd ../..

# 5. Configure environment
cp .env.example .env
nano .env   # Add your API keys (see Configuration section)

# 6. Start Jarvis
./start_jarvis.sh
```

Open your browser at `https://your-server-ip` and log in with `jarvis/jarvis`.

> **Self-signed certificate:** Your browser will warn about the certificate on first visit. This is expected — accept the exception or install the certificate from Settings → SSL.

### systemd Service (Recommended for Production)

```bash
# Copy service files
sudo cp services/systemd/jarvis.service /etc/systemd/system/
sudo cp services/systemd/whatsapp-bridge.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable jarvis.service whatsapp-bridge.service
sudo systemctl start jarvis.service whatsapp-bridge.service

# Check status
sudo journalctl -u jarvis.service -f
```

### Port Overview

| Port | Service | Access |
|------|---------|--------|
| 443 | FastAPI (HTTPS) | External |
| 80 | HTTP → HTTPS Redirect | External |
| 6080 | websockify (noVNC bridge) | **Local only** |
| 5900 | x11vnc | **Local only** |
| 3001 | WhatsApp Bridge | Local only |

The desktop is reached **only** through `/novnc` on port 443, with a session token. Ports 5900 and 6080 bind to loopback: `x11vnc` runs with `-nopw`, and websockify used to serve noVNC without any authentication — anyone who could reach the host had mouse and keyboard, bypassing the portal login. `deploy/security/harden_vnc.sh` adds `-localhost` to every x11vnc start site (including the ones in Python — a `grep` over `*.sh` alone misses them), and `deploy/security/firewall.sh` installs a default-DROP packet filter for IPv4 *and* IPv6.

---

## Configuration

All configuration lives in `.env` (secrets) and `data/settings.json` (UI-managed settings). Most settings can be changed at runtime via the web UI.

### `.env` Reference

```env
# ── LLM Providers ──────────────────────────────────────────────
GOOGLE_API_KEY=your_gemini_api_key
ANTHROPIC_API_KEY=your_claude_api_key
OPENROUTER_API_KEY=your_openrouter_api_key

# Local Ollama (no key needed — just set the base URL)
OLLAMA_BASE_URL=http://localhost:11434

# ── Authentication ──────────────────────────────────────────────
JARVIS_USERNAME=jarvis
JARVIS_PASSWORD=jarvis          # Change this in production!
SECRET_KEY=change-me-to-a-random-string

# ── WhatsApp ────────────────────────────────────────────────────
WA_ALLOWED_NUMBERS=+4915112345678,+4917098765432  # Comma-separated whitelist

# ── Optional ────────────────────────────────────────────────────
DISPLAY=:1                      # X11 display for desktop control
KNOWLEDGE_DIRS=/data/docs,/home/jarvis/notes  # Watched knowledge folders
```

### Switching LLM Providers

Use the Settings panel in the web UI to switch providers and models at runtime — no restart required. Multiple profiles can be saved and activated with one click.

---

## Multi-User Chat

The `/userchat` endpoint provides a **real-time P2P chat** between all users currently logged into Jarvis.

### Features
- **Live presence** — see who's online with colored status dots
- **Image gallery** — up to 4 images in a grid, tap to open fullscreen lightbox
- **Audio/Video players** — inline playback directly in the chat bubble
- **File chips** — PDF and other attachments with download links
- **Lightbox** — fullscreen image viewer with keyboard navigation (← → Esc) and save button
- **Context menu** — right-click or long-press (mobile) on any attachment: Save / Forward
- **Forward** — send any file to another online user with one tap
- **Emoji reactions** — react to any message
- **Typing indicators** and read receipts

Attachments are transferred peer-to-peer through the server — Jarvis does **not** analyze them.

---

## Multi-Agent System

Jarvis can spawn **autonomous sub-agents** that work in parallel with the main agent.

```python
# In a task, the main agent can spawn sub-agents:
# {"_spawn_agent": true, "label": "Research Agent", "task": "Find all papers about X"}
```

- Each sub-agent has access to all tools and skills
- Sub-agents appear as cards in the sidebar (purple = sub-agent, green = main)
- Real-time streaming output for every agent
- Sub-agents are fully autonomous — no interruptions or confirmations

This enables patterns like: *"Simultaneously research topic A and B, then merge the results."*

### Role Agents & `delegate()`

`spawn_agent` is fire-and-forget with the full toolbox. **Role delegation is the opposite:** an admin defines named roles under *Settings → Orchestrator* — each with its own system prompt, tool whitelist, optional LLM profile, reasoning depth and step limit. The main agent then gets one tool:

```
delegate(role="image_builder", task="Render a 16:9 title image for the quarterly report")
```

It hands off, **awaits** the result, and keeps working with it.

The security rule is a single formula:

```
effective tools = role whitelist ∩ (caller's tools − blocklist) − delegate
```

**A role can only take away.** Reversing that direction would make "role X may use tool Y" the most convenient way around the network-user blocklist — a permanent privilege escalation for anyone allowed to delegate. The caller's identity, privilege level, internet and SAP flags are passed through unchanged, and every gate runs as usual. Role agents cannot delegate further (recursion guard), and there is a hard cap of 8 delegations per task.

Getting a model to actually delegate is not automatic. Measured with a 35B local model and 70 tools, the tool description alone was **not** enough — it answered "image generation is unavailable" while both the tool and the role existed. Three levers, in this order, fixed it: the role list in the tool description, the same list repeated in the system prompt, and a deterministic fallback that hands over when a tool fails *and* an active role carries exactly that tool with its own profile.

---

## Skill System

Skills extend Jarvis with new capabilities. Each skill is a self-contained Python package:

```
skills/
  my_skill/
    skill.json    # Manifest
    main.py       # Tool definitions
    requirements.txt  # Optional extra dependencies
```

### `skill.json` Structure

```json
{
  "name": "my_skill",
  "display_name": "My Awesome Skill",
  "version": "1.0.0",
  "description": "Does something awesome",
  "author": "Your Name",
  "tools": ["MyTool"],
  "config_schema": {
    "api_endpoint": {
      "type": "string",
      "description": "The API endpoint URL",
      "required": true
    }
  }
}
```

### `main.py` Structure

```python
from backend.tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something specific and useful"

    async def execute(self, param1: str, param2: int = 10) -> str:
        # Your implementation here
        return f"Result: {param1} with {param2}"

def get_tools(config: dict) -> list:
    return [MyTool(config=config)]
```

### Built-in Skills

**Core** (on by default — the agent's basic hands and eyes)

| Skill | Description |
|-------|-------------|
| `shell` | Run bash commands (sandboxed for network users) |
| `filesystem` | Read, write and manage files (path-confined) |
| `knowledge` | Hybrid RAG over local documents (FAISS + BM25) |
| `memory` | Persistent store for facts and preferences |
| `screenshot` | Capture the desktop (feeds back into the LLM context) |
| `desktop` | Mouse, keyboard and window control (X11) |
| `cron` | Create, list and delete scheduled jobs (admin only) |
| `office` | Create and edit Word, Excel, PowerPoint, PDF — incl. the `xlsx_*` and form-PDF tools |

**Integrations**

| Skill | Description |
|-------|-------------|
| `email` | Exchange (EWS + IMAP/SMTP fallback), per-user mailboxes and rules |
| `excel-addin` | Chat task pane against the currently open workbook |
| `jira` / `confluence` | Atlassian Server/Data-Center — search, read, work on issues and pages |
| `sap` | Read-only access to S/4HANA, ECC, BW/4HANA, HANA Cloud, Datasphere |
| `kundenverwaltung` | IBS customer-management API (ticket search by keyword) |
| `google` | Gmail, Drive and Calendar via OAuth2 |
| `whatsapp` | Send/receive WhatsApp messages (incl. voice notes) |
| `telegram` | Telegram bot — receives messages, sends replies |
| `browser_control` | CDP + xdotool browser automation |
| `vision` | Real-time face recognition (USB/IP camera) |

**Areas and agents**

| Skill | Description |
|-------|-------------|
| `short-tracks` | Drop zones with a stored prompt (`/tracks`) |
| `support_assistant` | Support UI (`/support`) with RAG and Jira ticket search |
| `userchat` | User-to-user direct messages (`/userchat`) |
| `agent_orchestrator` | Named role agents + `delegate(role, task)` |
| `agent_autonomy_kit` | Proactive task management via `QUEUE.md` |
| `cognitive_evolution` | Self-improving agent (analyze → propose → validate → apply) |
| `coding_agent` | Autonomous coding agents (staff-engineer workflow) |
| `claude_subagent` | Claude Code hands scoped coding tasks to Jarvis (`/claude`) |
| `claude_bridge` | Delegate tasks to the Claude desktop app (xdotool) |

**Appearance**

| Skill | Description |
|-------|-------------|
| `branding` | Replace name, colors and logo with your own (white-label) |
| `avatar` | Talking assistant figure in the chat |
| `example_skill` | Template for new skill development |

Skills declare their own pip and apt dependencies in `skill.json`; enabling one installs them in the background, and **Purge** removes them again — with a shared-use check so it never uninstalls a package another skill still needs.

Beyond skills, the backend also exposes an **MCP client** (`backend/mcp_client.py`) so Jarvis can connect to external Model Context Protocol servers.

### Installing a Skill

1. Place the skill folder under `skills/`
2. Enable in the web UI under Settings → Skills (hot-reload, no restart needed)

---

## 🔌 OpenClaw Skill Ecosystem

> **Jarvis is fully compatible with the [OpenClaw](https://github.com/steipete/gogcli) skill format.**

OpenClaw is a growing ecosystem of AI agent skills. Jarvis can import any OpenClaw skill package directly.

### Built-in OpenClaw Skills

| Skill | Description |
|---|---|
| `openclaw_gmail` | Full Gmail integration via gog CLI (send, read, search, manage) |
| `agent_orchestrator` | Orchestrate multiple sub-agents for complex parallel tasks |
| `agent_autonomy_kit` | Heartbeat monitoring, task queuing, autonomous operation |

### Importing an OpenClaw Skill

```bash
# Drop it into the skills/ directory
cp -r my_openclaw_skill/ skills/

# Enable in UI: Settings → Skills → toggle ON
```

---

## Email Automation & Outlook Add-in

> Skill `email` — **off by default**. Enabling it installs `exchangelib`.

Connect the in-house **Exchange**: EWS first, IMAP/SMTP as a fallback. Server settings belong to the admin, the mailbox belongs to the user — deliberately, because a user-editable "IMAP server" field would be the way to send company credentials to a foreign host.

### Rules

Every user writes their own rules in plain language. When a new message arrives, the rule's prompt runs and **the model chooses the action**: reply, draft, move, forward, send, delete.

That combination — a stored prompt that later starts an agent run with nobody present, plus foreign text in the same prompt — is the most dangerous persistence substrate in the project. Three barriers, none of which is sufficient alone:

1. **Actor binding** — the run carries the rule owner's identity and is *always* unprivileged. `privileged` is hard-coded `False` and is not a field of the rule. There is no path to system rights here, not even for an admin. A rule without an owner never runs.
2. **Tool whitelist** — the same hard barrier used for role agents, checked *before* execution, not merely in the tool list the model sees. The business-systems area contains **read-only** tools only: an incoming email must not be able to create a ticket.
3. **Trigger conditions live in fields, not in the prompt** — sender and subject filters are evaluated by the runner *before* a model ever sees the message. Wildcards are supported. Saving a rule whose prompt tries to express a sender condition is **rejected**.

The mailbox is never a tool parameter: it comes from a context variable set per call, so a model cannot choose whose mailbox it works in, and an injected sentence has no field to reach for.

### Does the injection protection work? Measured, not claimed

Test setup: a rule that may only act on a sender that never occurs — so **any** tool call is itself the proof that the message steered the agent. Plus a positive control, because "held" proves nothing if the rule could not have acted at all.

**Before: 3 of 4 held.** What got through was a message that *rebuilt the prompt's own section markers* and appended a forged rule section. Structural, not bad luck — the markers were fixed, guessable text.

Three countermeasures, then **6 of 6**:

- an **authenticity token** generated per run, embedded in every genuine marker
- **defanging**: marker-like lines in foreign text get a `| ` prefix — still readable (an invoice has separator lines) but no longer shaped like a marker
- **visibility without lockout**: foreign text is classified but never blocks, because the text comes from a stranger — a lockout would be a way to lock any user out by email

The remaining risk is named openly: the prompt layer is probabilistic, not certain. The hard boundary is the tool cut — and within it, sending to arbitrary addresses is possible. Anyone who wants that excluded gives the rule mail tools without send tools.

### Outlook Add-in

An Office **web add-in** (XML manifest, `Mailbox 1.3`) brings the area into a task pane:

- process the **selected message** with a rule, right from Outlook
- generate a **reply preview**, edit it, send on a button press — the suggestion run has **no tools at all**, so an injection can trigger nothing here, and no language model runs on send
- sign in **without a password** via the Exchange identity token — verified against the configured EWS address as the trust anchor, so nobody can present a validly signed token from *some other* Exchange

> Microsoft's **new** Outlook for Windows does not support on-premises Exchange accounts at all — independently of add-ins. Supported: classic Outlook (M365 / Office 2021+) and Outlook on the web. Full guide: [`docs/outlook-addin.md`](docs/outlook-addin.md).

---

## SAP Analysis Area

> Skill `sap` — read-only by construction.

A dedicated `/sap` area for management, reachable only for users on the SAP allow-list. Pick an analysis template, add a free-text question if you like, and the agent evaluates and answers with figures and sources.

**24 templates in 6 categories**, cut for a stock corporation: operational analysis, segment reporting (IFRS 8), expected credit losses (IFRS 9), group consolidation, internal controls and separation of duties, VAT/Intrastat, ESG/CSRD, and forecast deviation as an early warning — the last one states in its own task text that it does **not** replace the legal assessment.

- **Read-only is the area's promise**, held twice: hard in the SAP client (OData `GET` only, SQL `SELECT`/`WITH` only, RFC whitelist) *and* in the catalog — a test rejects any template text containing a writing keyword, because otherwise the run ends in an error message instead of an analysis.
- **Personal SAP accounts**: each user stores their own credentials; the admin's account becomes the shared read-only fallback. Before this, everyone with access inherited the permissions of one server account.
- **Certificate pinning** instead of switching validation off: exactly one certificate becomes the trust anchor, validation stays on, a change aborts and has to be accepted deliberately. Whether pinning would actually work is **measured** with a third handshake, not inferred.
- The **history stores the question, never the result** — business figures have no business in browser storage.

---

## Short Tracks

> Skill `short-tracks` — off by default.

A board of named **drop zones**, each with a stored prompt. Drag a file or a URL onto one and it runs: result on the card, generated files as download chips. Admins create global zones, every user creates their own. Queue with an adjustable concurrency limit; per zone you choose "each file separately" or "all together".

Why a normal user may store prompts here, when that is otherwise an admin matter: the run only starts because a human dropped something on it, it carries that person's identity, it is **always unprivileged**, and its toolset is a whitelist drawn from admin-approved areas (read + document generation is the default; knowledge, read-only business systems and shell must be switched on).

Injection probes here went **1 of 6 → 6 of 6**. Defanging marker lines was not enough on its own — the line loses its *shape*, not its *meaning*. What worked: repeating the actual task **verbatim at the very end** of the prompt (the forged marker had simply been closer to the answer), breaking structure words inside foreign text so they cannot be rebuilt, and a per-run authenticity token.

---

## WhatsApp Integration

Jarvis uses [Baileys v7](https://github.com/WhiskeySockets/Baileys) to connect to WhatsApp Web — **no official API or business account required**.

### Setup

1. Start the WhatsApp bridge: `systemctl start whatsapp-bridge.service`
2. Open `https://your-server` → Settings → WhatsApp
3. Scan the QR code with your WhatsApp app
4. Add your number to `WA_ALLOWED_NUMBERS` in `.env`

### Voice Messages

Send Jarvis a voice note — it's automatically transcribed using **faster-whisper** (runs locally on CPU, no cloud):

```
You: [Voice note: "Check if there's anything urgent in my email today"]
Jarvis: "Found 3 emails marked as urgent. Here's a summary: ..."
```

### Security

Only numbers listed in `WA_ALLOWED_NUMBERS` can send tasks to Jarvis. Self-chat messages and bridge feedback loops are automatically filtered.

---

## Knowledge Base

Drop documents into watched folders and Jarvis can search them during tasks.

### Supported Formats
- PDF (`.pdf`) — full text extraction, OCR for scanned pages
- Word, Excel, PowerPoint (`.docx`, `.xlsx`, `.pptx`)
- Images (`.png`, `.jpg`) — OCR via tesseract
- Plain text (`.txt`, `.md`) and any text format

When the text layer of a PDF turns out to be **damaged** — a broken font cmap turns `01.07.2026` into `OL.O7.2026` while the character count looks perfectly healthy — Jarvis measures both readings on a two-page sample and only re-reads the document with OCR if OCR actually wins.

### How Search Works

Every query runs through three channels, fused by Reciprocal Rank Fusion:

| Channel | Purpose |
|---------|---------|
| **Semantic (full query)** | Meaning of the question as asked |
| **Semantic (content words)** | Same, with question filler removed — filler measurably drags the query vector away |
| **Lexical (BM25)** | Exact identifiers, error codes, product names — where embeddings are structurally weak |

Chunking is 200 words with 40 words overlap (kept under the 512-token limit of the embedding model, or the tail would be silently truncated and unfindable). Results are filtered by an absolute *and* a relative score cut; self-written learning notes are down-weighted so they cannot become the top hit for the very question they were named after.

A **TF-IDF index** remains as a fallback when the vector stack is unavailable.

### Knowledge Groups

Documents can belong to several logical groups; a search can be scoped to one. The group filter is applied **inside** the search — not afterwards — because post-filtering silently loses hits: the relative score cut would otherwise measure against a top hit from a different group.

> Knowledge groups organize and scope. They are **not** a read barrier — every authenticated user can reach every group's content through chat.

### Configuration

```env
KNOWLEDGE_DIRS=/home/jarvis/docs,/opt/company-wiki
```

Or configure via the Settings UI. Files are indexed automatically on change.

### Sync Between Sites

Several Jarvis instances in one network can share knowledge one-way. An admin at site A shares a folder (🔗 on the folder row) and gets one token; site B adds the site and **pulls** it. The result is a local mirror *and* RAG entries.

- **Incremental** via manifest + SHA-256; the receiver compares against the stored manifest **and** the disk, so a file deleted by hand comes back
- **TLS pinned in the transport layer**, not checked afterwards — the confirmed certificate is the only trust anchor, so the token never travels to an unverified peer
- The **mirror is write-protected** (HTTP 409, not 403 — no permission is missing, the folder is externally owned) and an existing knowledge folder can never be chosen as a target, because the first sync would delete whatever else is in it
- Revocation and outage **leave the copy in place** and report the reason in plain language

> Mirrored knowledge is readable by **all** users at the receiving site. Knowledge groups organize, they do not restrict reading. What you do not want everyone to see, you do not mirror.

### Knowledge Editor Permissions

Under **Settings → Security → Active Directory**, you can restrict who is allowed to add, edit, or delete knowledge:

- **Allowed Editors** — comma-separated usernames (e.g. `mueller,schmidt`)
- **Editor Group** — AD group DN (e.g. `CN=Knowledge-Editors,OU=Groups,DC=firma,DC=local`)
- Empty = all authenticated users may edit (default)
- Local admin users are always allowed

---

## Vision & Face Recognition

The optional **Vision Skill** adds real-time face recognition using [face_recognition](https://github.com/ageitgey/face_recognition) (dlib).

### Features
- Detect and identify faces from USB camera or IP camera (RTSP/HTTP)
- Per-person configurable actions:
  - **Webhook** — HTTP POST to any URL
  - **LLM Prompt** — trigger a Jarvis task (e.g. "Greet {name} and unlock the door")
  - **Log only** — silent event log
- Configurable tolerance (0.0–1.0) and cooldown per person
- Training via the Settings UI — upload photos per person
- Supports HOG (fast, CPU) and CNN (accurate, GPU) detection models

### Setup
1. Enable the Vision Skill in Settings → Skills
2. Add people in Settings → Vision → Profiles
3. Upload training photos and click "Train"
4. Configure actions per profile
5. Start the camera feed

---

## AD/LDAP & Security

### Active Directory / LDAP Login

Jarvis supports domain logins without joining the domain — the server only needs network access to the Domain Controller.

```
Settings → Security → Active Directory / LDAP
```

| Field | Description |
|-------|-------------|
| Domain Controller | IP or hostname of your DC |
| Domain | e.g. `firma.local` |
| Allowed Users | Comma-separated whitelist (empty = all AD users) |
| Allowed Group | AD group DN — takes precedence over user list |
| Allowed Editors | Who may edit the knowledge base |
| Editor Group | AD group for knowledge editors |

- TLS / StartTLS is attempted automatically
- Group membership is checked and cached at login time
- Local admin accounts are always accessible regardless of AD config

### Security Layer & Sandbox

Jarvis is designed to be exposed to non-admin (network/domain) users. All limits are **enforced in the tool dispatch (in code)** — not merely stated in the system prompt — so they can't be bypassed via prompt injection, encoded payloads, or poisoned "learned facts".

- **Shell sandbox:** commands from network users run as an unprivileged OS user (`runuser`) in a scratch workspace; system-changing commands, obfuscation (base64/eval/pipe-to-shell) and secret/root paths are blocked.
- **Filesystem confinement:** writes limited to the workspace, reads limited to knowledge/work directories; secrets, root and system areas are denied (symlinks resolved to prevent escape).
- **Attack detection & auto-lockout:** jailbreak / prompt-injection / Base64 attempts are logged as itemized incidents; repeated violations lock the account automatically (local admins are exempt; only a local admin can unlock).
- **No privilege escalation:** sub-agents inherit the caller's confinement; "learned facts" are treated as untrusted context and a top-priority safety rule can't be overridden.
- **Configurable** under `Settings → Security` (attack-prevention panel, sandbox status, violation log). Full technical write-up is available in-app via the ❓ button there.

> The hard guarantee comes from the OS sandbox; the pattern-based checks are defense-in-depth. Enable the OS sandbox by provisioning an unprivileged user and tightening file permissions (see in-app docs).

### Two-Factor Authentication (TOTP)

Every user can enable 2FA via **Settings → Security → 2FA** (Google Authenticator, Authy, or any TOTP app compatible with RFC 6238).

### Password Management

Local users can change their password via **Settings → Security → Change Password**.

---

## Multimedia Attachments

All Jarvis chat interfaces support rich file attachments.

### Main Chat (`/`)

| File Type | LLM Handling |
|-----------|-------------|
| Images (JPG, PNG, GIF, WebP, …) | Sent directly to LLM as vision input |
| Audio (MP3, WAV, OGG, M4A, …) | Transcribed via Whisper, text sent to LLM |
| Video (MP4, WebM, …) | Audio track transcribed via Whisper |
| PDF | Text extracted via pypdf, injected as context |

Supports all major LLM providers:
- **Gemini**: native multimodal (images sent as bytes)
- **Claude/Anthropic**: images as base64 content blocks
- **OpenAI-compatible**: images as `image_url` content blocks

### PWA Chat (`/chat`)

Full attachment support with **chat history persistence** (localStorage, last 120 messages). History is restored on next login with date separators and session markers.

### User Chat (`/userchat`)

Attachments are transferred as-is between users — the LLM is not involved. Images appear in a gallery grid, audio/video as inline players, PDFs/files as download chips.

**Attach UI features:**
- Drag & Drop onto the message area
- Preview bar with thumbnail chips before sending
- Toast notification for unsupported formats
- Right-click / long-press context menu on received files: **Save** or **Forward**
- Lightbox with keyboard navigation (← → Esc)

---

## Feedback & Self-Improvement

After every Jarvis response, **👍 👎 ❌ feedback buttons** appear inline:

| Rating | Effect |
|--------|--------|
| 👍 Positive | Logged as positive example |
| 👎 Negative | LLM analyzes response, generates 3–5 better alternatives, derives learning rule |
| ❌ Wrong | Same as negative + marks as factually incorrect |

Learning rules are stored in the knowledge base and influence future responses immediately — no retraining, no manual configuration.

Available in: Web Chat, Android App, iOS PWA, Windows App.

---

## Cognitive Evolution

The **Cognitive Evolution Skill** (`skills/cognitive_evolution/`) gives Jarvis the ability to extend and improve itself through a structured 4-phase cycle:

```
Analyze → Propose → Validate → Apply
```

| Tool | Description |
|------|-------------|
| `evolution_analyze` | Identifies gaps and plans the required change |
| `evolution_propose` | Generates code (new skill or patch), saves as proposal |
| `evolution_validate` | Syntax check + independent LLM security review |
| `evolution_apply` | Writes files, hot-reloads skills, updates engine |
| `evolution_cycle` | Runs all 4 phases via autonomous sub-agent |

### What it can do

- **Write new skills** — generates `skill.json` + `main.py`, activates them at runtime
- **Patch itself** — rewrites `engine.py` and reloads it via `importlib.reload()` without restart
- **Fix backend code** — delegates to the existing ReflectionTool (backup + LLM validation)
- **Update instructions** — modifies Jarvis's behavioral instruction files

### Safety

- Every proposal is validated by `py_compile` (syntax) and a second independent LLM
- Backups are created before any file is overwritten
- Skills are isolated in `skills/` — the core backend is only touched via explicit `code_fix` scope
- The skill is **disabled by default** — enable manually in Settings → Skills

---

## Client Apps

Use Jarvis from anywhere — browser, desktop, or phone. Every client talks to the same server over HTTPS/WebSocket and shares login, chat history, and attachments.

| Platform | Client | Highlights |
|----------|--------|-----------|
| **Web** (any OS) | Built-in web UI / PWA | Full feature set, installable to the home screen |
| **Windows** | Native Go client (`windows-app-go/`) | Tray, local speech-to-text, animated avatar, auto-update |
| **Android** | Native app (`android/`, Kotlin/Compose) | Streaming chat, voice input, attachments, push |
| **iOS** | PWA today · native app on the roadmap | Add-to-Home-Screen, mic input, offline shell |

### 🪟 Windows App (native, Go)

A lightweight **native** Windows client under `windows-app-go/` — no browser required:
- **System-tray** integration, always a click away
- **Local speech-to-text** — talk to Jarvis hands-free (runs on-device)
- **Animated avatar** with spoken/text responses
- Real-time **WebSocket** connection to the agent
- **Auto-update** (pulls the latest signed release)

```bash
cd windows-app-go && bash build.sh
```

### 🤖 Android App (Kotlin / Jetpack Compose)

A native, **signed** Android app under `android/`:
- Full Jarvis chat with **streaming** responses
- **Voice input** and multimedia **attachments** (image / audio / video / PDF)
- 👍 👎 ❌ feedback, optional **push notifications**
- **Active Directory / LDAP** domain login

Build: open `android/` in Android Studio and run (release builds are signed via a `.jks` keystore).

### 🧩 Office Add-ins

Two Office web add-ins put Jarvis where the work already happens — both served by this server, both signing in without a password where the platform allows it:

| Add-in | What it does |
|---|---|
| **Outlook** | `/email` in a task pane: process the selected message with a rule, preview and edit a reply before sending. Classic Outlook and Outlook on the web. |
| **Excel** | A chat window against the **currently open workbook** — ask about the sheet in front of you, let changes be applied. |

The Outlook manifest is **generated per server**, never kept as a file: every URL inside it has to point at *this* installation, and a repo copy would have to be edited per server. The task pane also tells you when the installed manifest is out of date — Microsoft only auto-updates add-ins from the store, so for an in-house Exchange it stays `Remove-App` + `New-App`.

### 🍎 iOS

No native iOS app is required today — open `https://your-server/chat` in Safari → **Add to Home Screen** for an app-like PWA:
- Microphone input (Web Speech API) & attachments
- Offline-capable shell (Service Worker), persistent chat history

A **native iOS client is on the roadmap** and can be prioritized on request.

---

## API Reference

The FastAPI backend exposes a REST + WebSocket API. Interactive docs available at `https://your-server/docs`.

### Authentication

All API calls require a Bearer token obtained via `/api/login`:

```bash
curl -s -X POST https://your-server/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"jarvis","password":"jarvis"}' | jq .token
```

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/login` | Authenticate, get Bearer token |
| `WS` | `/ws` | WebSocket — agent streaming, multi-user chat |
| `GET` | `/api/skills` | List all skills with status |
| `POST` | `/api/skills/{name}/enable` | Enable a skill |
| `POST` | `/api/skills/{name}/disable` | Disable a skill |
| `GET` | `/api/knowledge/files` | List indexed knowledge files |
| `POST` | `/api/knowledge/upload` | Upload file to knowledge base |
| `PUT` | `/api/knowledge/file_write` | Edit a knowledge file |
| `DELETE` | `/api/knowledge/files` | Delete a knowledge file |
| `POST` | `/api/knowledge/extract` | Extract knowledge from URL |
| `GET` | `/api/wa/logs` | WhatsApp message logs |
| `GET` | `/api/auth/ad_status` | Active Directory configuration + status |
| `POST` | `/api/feedback` | Submit response feedback |
| `GET` | `/api/memory` | Read persistent memory |
| `POST` | `/api/memory` | Write to persistent memory |

### WebSocket Protocol

```javascript
const ws = new WebSocket('wss://your-server/ws');

// Run an agent task
ws.send(JSON.stringify({
  type: 'task',
  text: 'Take a screenshot of the current desktop',
  token: 'your-bearer-token',
  lang: 'de',  // optional: 'de' or 'en'
  attachments: [  // optional
    { name: 'photo.jpg', mime_type: 'image/jpeg', data: '<base64>' }
  ]
}));

// Receive messages
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  // msg.type: 'status' | 'agent_event' | 'llm_stats' | 'agent_list' | 'dm'
  // msg.highlight: true → LLM response text
  // msg.agent_id: which agent sent this
};

// User-to-user DM
ws.send(JSON.stringify({
  type: 'dm',
  to: 'other_user',
  text: 'Hello!',
  token: 'your-bearer-token',
  attachments: []  // optional
}));

// Stop running agent
ws.send(JSON.stringify({ type: 'control', action: 'stop', token: '...' }));
```

---

## Contributing

Contributions are very welcome! Here's how to get involved:

### 🐛 Reporting Bugs

Open an issue at [github.com/dev-core-busy/jarvis/issues](https://github.com/dev-core-busy/jarvis/issues) and include:
- Your OS and Python version
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs (`journalctl -u jarvis.service`)

### ✨ Suggesting Features

Open an issue with the `enhancement` label. Describe the use case, not just the solution.

### 🔧 Submitting Code

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-new-skill`
3. Make your changes (see conventions below)
4. Test thoroughly
5. Submit a pull request

### Development Conventions

- **Code comments:** German preferred (project convention / *Projektkonvention*)
- **Commit messages:** German, descriptive
- **CSS:** Use `var(--text-primary)`, `var(--bg-glass)`, `var(--accent)` etc. — no hardcoded colors
- **Frontend:** Pure Vanilla JS, no frameworks, no build system
- **Secrets:** Never commit `.env` files or API keys
- **numpy:** Must stay `< 2.1` (VM lacks SSE4.2 / x86-v2 support)
- **Existing files:** Always use Edit (targeted diff) — never overwrite with Write (risk of 0-byte files)

### Writing a New Skill

The fastest way to contribute is building a new skill. Use `skills/example_skill/` as your template:

```bash
cp -r skills/example_skill skills/my_new_skill
# Edit skill.json and main.py
# Enable in Settings → Skills
# Submit PR!
```

---

## Third-Party Licenses

Jarvis is built on the shoulders of excellent open-source projects:

| Library / Tool | License | Link |
|---------------|---------|------|
| FastAPI | MIT | https://github.com/tiangolo/fastapi |
| uvicorn | BSD-3-Clause | https://github.com/encode/uvicorn |
| python-dotenv | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| ldap3 | LGPL-3.0 | https://github.com/cannatag/ldap3 |
| Baileys (WhatsApp) | MIT | https://github.com/WhiskeySockets/Baileys |
| faster-whisper | MIT | https://github.com/SYSTRAN/faster-whisper |
| pypdf | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| ChromaDB | Apache-2.0 | https://github.com/chroma-core/chroma |
| sentence-transformers | Apache-2.0 | https://github.com/UKPLab/sentence-transformers |
| face_recognition | MIT | https://github.com/ageitgey/face_recognition |
| noVNC | MPL-2.0 | https://github.com/novnc/noVNC |
| websockify | LGPL-3.0 | https://github.com/novnc/websockify |
| xdotool | MIT | https://github.com/jordansissel/xdotool |
| openclaw/gog CLI | MIT | https://github.com/steipete/gogcli |
| Openbox | GPL-2.0 | http://openbox.org |
| x11vnc | GPL-2.0 | https://github.com/LibVNC/x11vnc |

Full license texts are included in the `LICENSES/` directory.

---

## License

Jarvis AI Desktop Agent is licensed under the **Apache License 2.0 (Apache-2.0)**.

This means:
- ✅ Free to use, modify, and distribute — for personal and commercial purposes
- ✅ May be embedded in proprietary/closed-source products; no obligation to publish your changes
- ✅ Includes an explicit patent grant
- ⚠️ Keep the copyright/`NOTICE` and license notices; mark files you changed

See [LICENSE](LICENSE) and [NOTICE](NOTICE) for the full text. Third-party
components remain under their own licenses (see *Third-Party Licenses* above).

---

<div align="center">

**Built with ❤️ for the open-source community**

[jarvis-ai.info](https://jarvis-ai.info) · [GitHub](https://github.com/dev-core-busy/jarvis) · [Issues](https://github.com/dev-core-busy/jarvis/issues)

*"The best way to predict the future is to automate it."*

Developed by Andreas Bender with [Claude](https://claude.ai) (Anthropic) – code, architecture & landing page.

© 2026 Andreas Bender · Licensed under [Apache-2.0](LICENSE)

</div>
