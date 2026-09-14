# 🌟 GitCurator

> **Autonomous AI-powered GitHub profile manager and repository curator.**

GitCurator acts as your personal GitHub manager. It audits your repositories, designs and continuously updates your personal profile README, optimizes repository metadata with tailored descriptions and discoverability topics, generates human-friendly release changelogs, and detects stale or empty projects—powered by the **Google Gemini API** and **GitHub REST/GraphQL APIs**.

---

## ⚡ Key Features

1. **Profile README Auto-Updater (`gitcurator update-readme`)**
   - Scans pinned repositories, top languages, recent commit events, and contributions.
   - Leverages **Gemini 3.6 Flash** to draft a polished, aesthetic, and developer-forward profile `README.md`.
   - Directly commits to your special `username/username` profile repository or exports previews.

2. **Repository Hygiene & Stale Repo Cleaner (`gitcurator audit` & `gitcurator cleanup`)**
   - Identifies stale repositories (customizable inactivity threshold in months).
   - Flags empty repos, unchanged forks, missing `README`, missing `LICENSE`, or missing descriptions.
   - Interactive safety controls to archive or delete with strict confirmations and full `--dry-run` support.

3. **Intelligent Metadata Manager (`gitcurator update-metadata`)**
   - Reads repository code structure and README context to synthesize concise, impactful descriptions.
   - Generates 5–8 targeted GitHub topics/tags for discoverability.
   - Detects cryptic or messy repo names and suggests cleaner naming alternatives.

4. **Release & Changelog Tracking (`gitcurator changelog`)**
   - Compares commit histories since the latest tag or release.
   - Performs automated **Semantic Versioning (SemVer)** bump analysis (`major`, `minor`, `patch`).
   - Generates Keep-a-Changelog compliant release notes, updates `CHANGELOG.md`, and can publish official GitHub Releases.

5. **Safety, Logging, and Automation**
   - Non-destructive by default with `--dry-run` across every command.
   - Audit trail persisted in `activity_log.json` and visualizable via `gitcurator logs`.
   - Ready-to-use GitHub Actions workflow (`.github/workflows/profile-update.yml`) for automated cron updates.

---

## 🚀 Quick Start

### 1. Installation

Clone or enter the directory, then install dependencies:
```bash
pip install -r requirements.txt
pip install -e .
```

### 2. Environment Configuration

Create a `.env` file in the project root (see `.env.example`):
```env
GITHUB_TOKEN=your_github_personal_access_token
GEMINI_API_KEY=your_gemini_api_key
```

> **Token Permissions Required:**
> - `repo` (Full control of private/public repositories)
> - `read:user` & `user:email`

### 3. Usage Examples

#### Profile README Auto-Updater
```bash
# Preview generated README without making changes
gitcurator update-readme --dry-run

# Preview and save generated markdown locally
gitcurator update-readme --dry-run --output my_preview.md

# Publish live to your GitHub profile repository (username/username)
gitcurator update-readme
```

#### Repository Hygiene & Audit
```bash
# View interactive table of all repositories and flags
gitcurator audit --threshold-months 6

# Preview archiving stale/empty repos (>6 months inactive)
gitcurator cleanup --dry-run --threshold-months 6

# Interactively archive stale repositories
gitcurator cleanup --threshold-months 6 --action archive
```

#### Metadata & Topics Enhancer
```bash
# Preview AI-suggested description & topics for a specific repository
gitcurator update-metadata <repo-name> --dry-run

# Interactively apply suggested metadata to a single repo
gitcurator update-metadata <repo-name>

# Curate all repositories
gitcurator update-metadata --all --dry-run
```

#### Changelog Generator & SemVer Assistant
```bash
# Analyze commits, suggest next version, and generate changelog preview
gitcurator changelog <repo-name> --dry-run

# Commit updated CHANGELOG.md and create a GitHub Release
gitcurator changelog <repo-name> --create-release
```

#### Audit History
```bash
# View recent actions and operations
gitcurator logs --limit 10
```

---

## ⚙️ Configuration (`config.yaml`)

Customize thresholds and behaviors in `config.yaml`:
```yaml
ai:
  model: "gemini-3.6-flash"
  temperature: 0.7

profile_readme:
  tone: "professional yet personable, modern tech-forward"
  featured_repos_count: 6

cleanup:
  stale_months_threshold: 6
  exclude_repos: []

safety:
  dry_run_default: false
  require_confirmation_for_destructive: true
  log_file: "activity_log.json"
```

---

## 🤖 Automated Schedule (GitHub Actions)

A workflow is provided at `.github/workflows/profile-update.yml` to automatically refresh your profile weekly. Configure your repository secrets:
- `GH_PAT_CURATOR`: Personal Access Token with repo scope.
- `GEMINI_API_KEY`: Google Gemini API Key.
