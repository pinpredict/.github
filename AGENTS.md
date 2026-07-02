# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The org-default `.github` repo for `pinpredict`. It holds **shared GitHub Actions reusable workflows and composite actions** consumed by every service repo (`trading`, `magellan`, `dis`, `replay`, `trader-tools`, `service-template`, etc.). No application code, no tests. Read `README.md` first — it is the consumer-facing contract and stays in sync with the YAML.

Callers pin to `@main` (intentional — we own all consumers; pre-tagging adds overhead without safety benefit at this team size). That means any change here propagates to every caller on next workflow trigger. Treat each edit as a potential blast radius across all service repos.

## Layout

- `actions/<name>/action.yml` — composite actions. Used as `uses: pinpredict/.github/actions/<name>@main`.
- `.github/workflows/<name>.yml` — reusable workflows. Used as `uses: pinpredict/.github/.github/workflows/<name>.yml@main`.

Static lint: `actionlint.yml` runs on every PR that touches `.github/workflows/**` or `actions/**/action.yml`, catching workflow syntax / expression / shell / `workflow_call` input-contract errors before they reach a caller as a runtime `startup_failure`. No build or test step — semantic changes still need a draft PR in a real caller pointing its `uses:` at your branch.

## Architectural contracts other repos depend on

### Service catalog: `.platform/services/<svc>.yaml`

`discover-services` and `chart-release.yml` both auto-discover services/charts from a caller's `.platform/services/*.yaml` files. The schema is defined and documented in `trading/.platform/services/README.md` (authoritative) and the parent `CLAUDE.md`. Fields this repo reads:

- `name`, `repositories.image`, `repositories.chart`
- `build.project`, `build.dockerfile` (default `Dockerfile`), `build.target` (default `production`), `build.sourcePaths[]`

`discover-services` **validates `build.dockerfile` exists on disk, `build.target` is a real `FROM ... AS <target>` stage, and `repositories.chart` resolves to a sibling `charts/<x>/Chart.yaml`** before emitting the matrix. The dockerfile/target checks catch multi-Dockerfile repos (trader-tools) where the silent default would build the wrong artifact (trader-tools#482 / pinpredict/.github#5). The chart check catches inline-sub-deployment shortcuts that chart-release's `charts/*/Chart.yaml` discovery silently skips, leading to `ImagePullBackOff` when the umbrella's image fallback resolves (dis#123/#128 / platform-gitops#538).

### Per-service IAM push role naming

Both `docker-release.yml` and `chart-release.yml` assume the deterministic role `arn:aws:iam::784682930591:role/xp-<name>-gha-push` (rendered by the Service XR composition in `platform-gitops`). If `matrix.role` is empty (un-migrated service/chart), the workflow falls back to `secrets.AWS_ROLE_ARN`. **Do not break this fallback** — some repos still rely on it.

Both workflows use a three-shot retry pattern (try / sleep 30 / retry / sleep 60 / retry) on `configure-aws-credentials` to survive the race where Crossplane is still creating the per-service role on first colocation. Incident reference: pinpredict/trading#616 (2-second race). Keep the retry pattern when editing AWS auth steps.

### Image / chart versioning and tagging conventions

- **ECR is the version record** (platform-gitops#1201): both release workflows resolve the next version as the highest strict-`X.Y.Z` tag in the service's ECR repo (image or `charts/<name>` OCI) plus one, then probe-and-bump past any existing candidate (ECR tags are immutable). Git tags are never read for versioning.
- **Release marker refs**: `refs/releases/image/<name>` and `refs/releases/chart/<name>` — one mutable ref per service, force-advanced to the released SHA on every successful push. They are the change-detection baseline for `discover-services` and chart-release's prepare job (legacy `image|chart/<name>/X.Y.Z` tag is the fallback until a service releases once with the marker in place). Not tags, so they don't feed Kargo's tag enumeration or the GitHub `create` webhook. Readers must fetch them explicitly (`+refs/releases/*:refs/releases/*`).
- **Dispatch publish notification**: after each successful push, both release workflows call `actions/notify-dispatch` — a signed POST (service, version, full SHA, run URL) through the public webhook-forwarder `/dispatch/ci` route, HMAC'd with the org `CI_WEBHOOK_SECRET` (reaches reusable workflows via `secrets: inherit`). Warn-only on failure: the EventBridge ECR-push backstop covers a missed call.
- **Chart sha alias**: chart-release aliases the pushed OCI chart as `X.Y.Z-<sha7>` (via `aws ecr put-image` on the same manifest — allowed under tag immutability) so the ECR-push backstop can recover commit provenance for charts, mirroring the image tag pair. Semver-prerelease form, so Kargo chart Warehouses ignore it.
- Per-service image tag: `image/<name>/X.Y.Z` (immutable git tag, pushed after successful ECR push). **Legacy mirror** — the direct notification above supersedes the `create`-webhook correlation; the tags are removed in #1201's final step once the new signals are verified.
- Per-chart tag: `chart/<name>/X.Y.Z` — same legacy status.
- Per-service config tag (Kargo freight for `<svc>-config` Warehouse): `vX.Y.Z+<svc>` — semver **build metadata** form (`+`), not pre-release (`-`). The `+` form passes `semverConstraint: ">=0.0.0"` cleanly; the pre-release form would require `>=0.0.0-0`. **This tag family stays** — it is genuine Kargo freight.

Pinpoint/Dispatch (our deploy correlator) hooks the GitHub `create` webhook on `image/<name>/*` tags — keep the tag format stable until the direct CI→Dispatch notification lands.

### `tag-config.yml` → platform-gitops dispatch

After tagging `vX.Y.Z+<svc>`, `tag-config.yml` mints a GitHub App token (`BOOTSTRAP_APP_ID` / `BOOTSTRAP_APP_PRIVATE_KEY` — the `pinpredict-argocd` App, ID 3187934) and fires `repository_dispatch` (event_type `service-config-tag`) into `platform-gitops` to seed missing pointer files. See `platform-gitops/docs/design/env-pinned-service-specs.md` §Bootstrap workflow.

### `pre-commit-advisory.yml` is non-blocking by design

It posts a sticky PR comment with hook output and fails the job (so engineers see a ❌), but is **not** in any repo's required-checks list. Scoped to PR diff (`--from-ref`/`--to-ref`) so engineers only see violations they introduced. If you ever wire a setup step (e.g. another language toolchain) into the advisory workflow, gate it behind an input that defaults to `false` — matches the existing `setup-dotnet` / `setup-node-pnpm` pattern.

## Editing playbook

- **Changing the docker matrix shape** in `discover-services/action.yml` means changing the corresponding consumer in `docker-release.yml` and (usually) the caller's `ci.yml` skeleton in `README.md` — keep all three in sync in one PR.
- **Bumping action versions** (`actions/checkout`, `aws-actions/*`, etc.) — bump both workflows together if they share the action; mismatched versions across the two release workflows have caused subtle behavior splits before.
- **Adding a new composite action** under `actions/`: add a row to the `## What's here` table in `README.md` and a usage block under `#### Language setup composites — usage` if it's a setup composite.
- **Force `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true`** is set on workflows that use older marketplace actions still pinned to Node 20 — leave it in place when copying steps.
- **Hard rule**: do not pre-tag this repo with `@v1` / `@v2` selectively — README's stance is "fix forward on main, only tag if blast radius bites." Don't introduce version tags without explicit discussion.

## Parent guidance

This repo inherits the org-wide `pinpredict/CLAUDE.md` (commit-message format, worktree workflow, en-US spelling, etc.). Anything in this file is repo-specific on top of that.
