# Fold AI — deployment guide

This folder is a complete, ready-to-deploy website. It has three parts:

- `index.html` — the site itself (chat, sidebar, everything)
- `api/chat.js` — a small server function that safely holds your API key and talks to Gemini on your behalf
- `bridge_server.py` — an *optional* helper you run on your own PC that lets Fold AI open apps/websites and scan your screen (see "Jarvis Bridge" below)

Your API key never appears in `index.html` or in anything a visitor's browser can see.

## Deploy on Vercel (free)

1. **Create a Vercel account** at vercel.com (you can sign up with GitHub, Google, or email).

2. **Get this folder onto Vercel.** Easiest path if you don't use GitHub:
   - Install the Vercel CLI: `npm install -g vercel`
   - In this folder, run: `vercel`
   - Follow the prompts (it will ask to link/create a project — accept the defaults)

   Or, if you use GitHub: push this folder to a new GitHub repo, then on vercel.com choose "Add New Project" → "Import" that repo.

3. **Add your API key as an environment variable** (this is the important step):
   - In your Vercel project dashboard, go to **Settings → Environment Variables**
   - Add a new variable:
     - Name: `GEMINI_API_KEY`
     - Value: paste a free key from aistudio.google.com
   - Save, then redeploy (Vercel will prompt you, or run `vercel --prod` again)

4. **That's it.** Vercel will give you a live URL like `fold-ai.vercel.app`. Open it on your phone, any device, anywhere — the chat will now actually work, because requests go through your backend, which has the real key.

## Connecting your own domain (e.g. www.foldai.com)

In the Vercel dashboard: **Settings → Domains** → add your domain, then update your domain registrar's DNS records the way Vercel shows you (usually one CNAME record). This part is between you and your domain provider — I can walk you through it once you've bought a domain if you don't have one yet.

## Jarvis Bridge (optional — screen scan, open apps/sites)

A website can never be given direct control of your computer — that's a
security boundary every browser enforces, not something this code can turn
off. `bridge_server.py` is the honest way around that: a tiny helper *you*
run on your own PC that Fold AI can talk to, only on that same computer.

1. On the computer you want Fold AI to control:
   ```
   pip install mss psutil pyautogui
   python bridge_server.py
   ```
2. Leave that terminal window open. It will print a token like:
   ```
   Your token:   3f9a1c...
   ```
3. Open Fold AI in your browser on that same computer → sidebar →
   **Jarvis Bridge** → paste the token → **Save & connect**.
4. You can now just type things like "open spotify", "what's the weather?",
   "how's my PC doing?", "make me a presentation on the water cycle", or
   "what's on my screen?" — Fold AI's AI decides on its own when to use
   each of these real tools:
   - `open_website` / `open_app` — opens things on your PC
   - `scan_screen` — describes what's currently on your screen
   - `get_weather` — via your browser's location, no bridge needed
   - Real-time web search (news, current events, anything recent) — this
     uses Gemini's own built-in Google Search, the same mechanism Jarvis's
     own `web_search.py` uses, so no separate setup needed
   - `get_system_stats` — your PC's live CPU/RAM/battery
   - `open_path` — opens a specific file or folder by path
   - `make_presentation` — generates and downloads a real .pptx file

This only works on whichever computer has `bridge_server.py` running — it
does not give control over any other device, and it never sends anything
over the internet except your normal chat traffic to your own Vercel
backend.

## If something doesn't work

- "Server error: Server is not configured with an API key yet." → the `ANTHROPIC_API_KEY` environment variable isn't set, or you need to redeploy after adding it.
- Chat still fails after deploying → double check the key was copied correctly (no extra spaces) and that your Anthropic account has available credits.
