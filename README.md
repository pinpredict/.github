# pinpredict/.github

Org-default repo for pinpredict. Holds shared GitHub Actions reusable workflows + composite actions consumed by service repos, and will hold future org-default surface (issue templates, SECURITY.md, profile README, etc.) as those are added.

Why `.github` and not a dedicated `github-actions` repo: `.github` is *the* GitHub convention for org-wide infrastructure. Putting reusable workflows here means one repo holds anything org-default — no recurring "which repo for which org-default" question.

## What's here

### Reusable workflows (`.github/workflows/`)

| File | Purpose |
|---|---|
| `docker-release.yml` | Matrix-based image build + push to ECR. Version = highest `X.Y.Z` tag in the ECR repo + 1 (ECR is the version record — platform-gitops#1201); advances the `refs/releases/image/<name>` marker ref and notifies Dispatch. No git tags or GitHub Releases. Caller passes a `matrix` input in the standard `{include:[...]}` shape. Optional `private-modules: true` mints a short-lived read-only `pinpredict-argocd` App token and exposes it to the build as BuildKit secret `id=gh_token` (`RUN --mount=type=secret,id=gh_token …`) — for Dockerfiles that fetch a private pinpredict module (e.g. `github.com/pinpredict/ppkit`) instead of vendoring it. Default false. |
| `chart-release.yml` | Auto-discovers `charts/*/`, skips charts unchanged since their `refs/releases/chart/<name>` marker ref, resolves the next version from the ECR OCI repo, packages, pushes (+ `X.Y.Z-<sha7>` provenance alias), advances the marker, notifies Dispatch. No git tags or GitHub Releases. No caller inputs. |
| `tag-config.yml` | Tags merges to main that touch `.platform/services/<svc>.yaml` with `vX.Y.Z+<svc>` (per-service Kargo `<svc>-config` Warehouse freight), then dispatches `service-config-tag` to platform-gitops so missing pointer files get seeded. |
| `actionlint.yml` | Lints GitHub Actions workflow YAML with [`actionlint`](https://github.com/rhysd/actionlint) at a pinned version. Self-runs on this repo when PRs/pushes touch `.github/workflows/**` or `actions/**/action.yml`; callers reuse it via `uses: pinpredict/.github/.github/workflows/actionlint.yml@main`. |

### Composite actions (`actions/`)

| Action | Purpose |
|---|---|
| `notify-dispatch` | POSTs a signed publish notification (service, version, SHA, run URL) to Dispatch's public `/dispatch/ci` route after a successful ECR push. Called by both release workflows; warn-only on failure (the EventBridge ECR-push backstop covers a missed call). |
| `configure-aws-with-retry` | Wraps `aws-actions/configure-aws-credentials` in a three-shot retry (try / sleep 30 / retry / sleep 60 / retry) to survive a first-colocation race with Crossplane minting the per-service `xp-<svc>-gha-push` role (pinpredict/trading#616). Inputs: `role-to-assume` (required), `aws-region` (default `us-east-1`). Shared by both release workflows. |
| `discover-services` | Reads `.platform/services/*.yaml` and emits a docker matrix of services whose docker-relevant files changed since their last release (baseline = `refs/releases/image/<name>` marker ref; legacy `image/<name>/*` tag fallback). Also emits `charts_changed`. |
| `validate-platform-service` | Pre-merge static + render check for added/modified `.platform/services/*.yaml`. Renders each via `charts/service-template` for every env in `environments[]` with all `renderXxx` flags forced on; verifies `repositories.chart` resolves to a real `charts/<x>/Chart.yaml`. Closes the gap from platform-gitops#544 — every dis-opticodds-props-streamer failure mode would have failed CI here. |
| `validate-reusable-inputs` | Cross-repo input validation for callers of `pinpredict/.github` reusable workflows. Diffs every `with:` block against the referenced workflow's `on.workflow_call.inputs` map; fails on unknown keys or missing-required keys. Closes the gap left by stock `actionlint`, which can't fetch remote reusable workflows (platform-gitops#1045). Runs automatically as a sibling job in `actionlint.yml`, so any consumer that already `uses:` that reusable workflow inherits it. |
| `setup-python-uv` | Install uv + a pinned Python version + (default-on) `uv sync`. |
| `setup-node-pnpm` | corepack + setup-node@v4 with pnpm cache + (default-on) `pnpm install --frozen-lockfile`. Accepts a `pnpm-filter` input for workspace filtering. |
| `setup-dotnet` | setup-dotnet@v5 with NuGet cache keyed on `**/*.csproj` + (default-off) `dotnet tool restore`. |
| `setup-go` | setup-go@v6 reading version from `go.mod`. Optional `private-modules: true` mints a short-lived read-only `pinpredict-argocd` App token and configures git + `GOPRIVATE` so `go`/`golangci-lint`/`goreleaser` fetch a private pinpredict module (e.g. `github.com/pinpredict/ppkit`) without vendoring — the non-Docker analogue of `docker-release.yml`'s `private-modules` secret. Default false. |

#### Language setup composites — usage

```yaml
# Python (dis, replay, magellan, trader-tools BFF)
- uses: pinpredict/.github/actions/setup-python-uv@main
  with:
    python-version: "3.13"   # optional; default "3.13"
    uv-sync: "true"          # optional; default true. Set "false" if the job
                              # only needs Python without dependency install.

# Node (trader-tools frontend / backend)
- uses: pinpredict/.github/actions/setup-node-pnpm@main
  with:
    node-version: "24"          # optional; default "24"
    pnpm-filter: "@pp/frontend" # optional; installs only that package + deps
                                  # via `--filter <value>...`. Empty = whole workspace.

# .NET (trading)
- uses: pinpredict/.github/actions/setup-dotnet@main
  with:
    dotnet-version: "10.0.x"  # optional; default "10.0.x"
    cache-nuget: "true"       # optional; default true. Keys on **/*.csproj
    tool-restore: "true"      # optional; default false. Required for csharpier etc.

# Go (service-template)
- uses: pinpredict/.github/actions/setup-go@main
  with:
    go-version-file: "go.mod" # optional; default "go.mod"

# Go, fetching a private pinpredict module without vendoring (e.g. k4a → ppkit)
- uses: pinpredict/.github/actions/setup-go@main
  with:
    private-modules: "true"                                          # opt-in; default false
    private-modules-app-id: ${{ secrets.BOOTSTRAP_APP_ID }}          # pinpredict-argocd App
    private-modules-app-private-key: ${{ secrets.BOOTSTRAP_APP_PRIVATE_KEY }}
```

## How to use

Pin callers to `@main`. We own all consumers, so version pinning adds overhead without safety benefit at this team size — `@main` gives the "edit once, propagate everywhere" property that's the whole point of centralizing. If blast radius ever bites, we add a `@v1` tag selectively for the workflows that broke; we don't pre-tag everything.

For workflows that touch secrets/OIDC, pin to an immutable SHA only if a security audit later requires it.

### Caller `ci.yml` skeleton

```yaml
name: CI
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
  workflow_dispatch:
    inputs:
      services:
        description: "Services to build: 'all' or comma-separated"
        type: string
        default: "all"

jobs:
  detect:
    runs-on: ubuntu-latest
    outputs:
      docker_matrix: ${{ steps.discover.outputs.docker_matrix }}
      charts_changed: ${{ steps.discover.outputs.charts_changed }}
    steps:
      - uses: actions/checkout@v6
        with: { fetch-depth: 0, fetch-tags: true }
      - id: discover
        uses: pinpredict/.github/actions/discover-services@main
        with:
          # Optional: extra source-pattern regex appended to every service's
          # change-detection (matched against files since the service's last
          # image tag). Use for shared code outside any single service.
          shared-source-patterns: |
            ^Dockerfile
            ^PinPredict\.Shared/

  # caller-owned language-specific test job here

  # Pre-merge gate for new/modified .platform/services/*.yaml. No-op
  # when the PR doesn't touch any engineer yaml; otherwise renders
  # each via service-template and fails CI on a broken yaml — the
  # gap that bit dis-opticodds-props-streamer onboarding. The app
  # token mint is needed because the action sparse-clones
  # `pinpredict/platform-gitops` (private) for service-template.
  validate-platform-services:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/create-github-app-token@v2
        id: pg-read-token
        with:
          app-id: ${{ secrets.BOOTSTRAP_APP_ID }}
          private-key: ${{ secrets.BOOTSTRAP_APP_PRIVATE_KEY }}
          owner: pinpredict
          repositories: platform-gitops
      - uses: actions/checkout@v6
        with: { fetch-depth: 0 }
      - uses: pinpredict/.github/actions/validate-platform-service@main
        with:
          github-token: ${{ steps.pg-read-token.outputs.token }}

  docker-release:
    needs: [detect, test]
    if: needs.detect.outputs.docker_matrix != '{"include":[]}'
    permissions: { id-token: write, contents: write }
    uses: pinpredict/.github/.github/workflows/docker-release.yml@main
    with:
      matrix: ${{ needs.detect.outputs.docker_matrix }}
    secrets: inherit

  chart-release:
    needs: detect
    if: needs.detect.outputs.charts_changed == 'true'
    permissions: { id-token: write, contents: write }
    uses: pinpredict/.github/.github/workflows/chart-release.yml@main
    secrets: inherit
```

And a thin `tag-config.yml`:

```yaml
name: Tag config
on:
  push:
    branches: [main]
    paths: ['.platform/services/*.yaml']
  workflow_dispatch:
    inputs:
      service:
        description: 'Service name to force-tag'
        required: false
        type: string

jobs:
  tag:
    uses: pinpredict/.github/.github/workflows/tag-config.yml@main
    secrets: inherit
    with:
      service: ${{ inputs.service || '' }}
```

## Org secrets consumed

`tag-config.yml` mints a token via the existing `pinpredict-argocd` GitHub App (App ID 3187934 — the same App Kargo uses) to dispatch `service-config-tag` to platform-gitops. Required org secrets, scoped to `platform-gitops, trading, magellan, dis, replay`:

- `BOOTSTRAP_APP_ID`
- `BOOTSTRAP_APP_PRIVATE_KEY`

Both are sourced from SSM (`/trading-platform-dev/config/argocd-github-app-{id,private-key}`). The App already has `Contents: write` on each consumer repo via Kargo, so no installation changes needed.

## Service catalog convention

`discover-services` and `chart-release.yml` both expect:

- `.platform/services/<svc>.yaml` per service, with `.name`, `.repositories.image`, optional `.build.project` / `.build.dockerfile` / `.build.target` / `.build.sourcePaths[]`.
- Per-service push role at `arn:aws:iam::784682930591:role/xp-<svc>-gha-push` (rendered by the platform-gitops Service XR composition).
- `secrets.AWS_ROLE_ARN` as the fallback role for un-migrated charts/services.
