# Revenue Recovery Desk — Landing Page

Static HTML/CSS marketing site for the app. Built to feel like Chaser /
Stripe / Linear marketing surfaces: large hero, scroll-revealed sections,
warm orange + amber + white palette, founder photo, team photos.

## Preview locally

```bash
python -m http.server 8765 --directory landing
# open http://localhost:8765
```

## Required: drop the 10 ChatGPT photos into `landing/assets/`

Use these exact filenames (referenced by `index.html`):

```
01-hero-portrait.jpg
02-desk-laptop.jpg
03-presenting.jpg
04-phone-call.jpg
05-team-of-three.jpg
06-team-of-four.jpg
07-two-person-consult.jpg
08-team-celebration.jpg
09-coffee-shop.jpg
10-environmental-portrait.jpg
```

Until they're present, the page will show broken-image placeholders where
photos would appear — everything else still renders.

## Replace `APP_URL` with your live Streamlit URL

In `index.html`, every `href="APP_URL"` button is a placeholder. Find-and-
replace `APP_URL` with the real link, e.g.:

```
https://fast-revenue-recovery.streamlit.app
```

## Deploy to Netlify (free, 5 minutes)

### Option A — drag-and-drop (simplest)
1. Go to https://app.netlify.com/drop
2. Drag the entire `landing/` folder onto the page
3. Netlify gives you a URL like `https://chipper-pony-1a2b3c.netlify.app`
4. In Netlify UI → Site settings → Change site name → pick something nicer
   like `revenue-recovery-desk` → URL becomes `revenue-recovery-desk.netlify.app`

### Option B — connect GitHub (auto-deploys on every push)
1. Netlify → "Add new site" → "Import an existing project" → GitHub
2. Pick `Fast-Revenue-Recovery` repo
3. Build settings:
   - Branch: `main`
   - Base directory: `landing`
   - Build command: *(leave empty)*
   - Publish directory: `landing`
4. Deploy. Future `git push` re-deploys automatically.

### Custom domain (later)
When you have a real domain, point its DNS at Netlify (Netlify gives the
exact records). Free SSL is automatic.
