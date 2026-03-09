# Streamlit Cloud 1:1 Click Checklist

Use this checklist exactly in Streamlit Community Cloud UI.

## A) Prepare Repo (GitHub)

- [ ] `app.py` is at repo root.
- [ ] `requirements.txt` exists at repo root.
- [ ] `data/snapshots/2530/graph_payload.json` exists in repo.
- [ ] `.streamlit/secrets.toml` is NOT committed.

## B) Create App (UI Click Path)

1. Open https://share.streamlit.io/
2. Click `Create app`.
3. In `Repository`, select your GitHub repo: `UST-Coursemap`.
4. In `Branch`, choose `main` (or your deployment branch).
5. In `Main file path`, type exactly: `app.py`
6. In `App URL` (optional), set a readable slug.
7. Click `Advanced settings`:
   - [ ] `Python version`: leave default (or select project-compatible 3.12+).
   - [ ] `Secrets`: optional; currently app UI does not expose cloud-side refresh actions.
8. Click `Deploy`.

## C) Optional Secrets (reserved for future crawler tooling)

Open app `Settings` -> `Secrets` and paste:

```toml
USTSPACE_USERNAME = "your_itsc"
USTSPACE_PASSWORD = "your_password"
```

Then click `Save` and `Reboot app`.

## D) Post-Deploy Smoke Test

- [ ] App opens without crash.
- [ ] Semester selector shows at least one semester (for example `2530`).
- [ ] Default graph is subject overview and is visible.
- [ ] Clicking a subject drills down to course-level graph.
- [ ] Search by `COMP 1021` works.
- [ ] Subject filter works.
- [ ] Completed courses list supports add/remove (one course per row, right-side red `-`).
- [ ] Double-click on node does NOT open external URL.
- [ ] `Download Current View (HTML)` works.

## F) Local Crawler Credential Note

- Local crawler runtime can use either shell env vars or `.env` loaded into current shell.
- Recommended PowerShell loader:

```powershell
Get-Content .env | ForEach-Object {
   if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
   $kv = $_.Split('=', 2)
   if ($kv.Length -eq 2) { [Environment]::SetEnvironmentVariable($kv[0], $kv[1]) }
}
```

## E) URL Acceptance Record (copy back to TODOTASK.md)

- Public URL:
- Deployment date (YYYY-MM-DD):
- Verified semester loaded:
- Smoke test result:
- Notes/issue links:
