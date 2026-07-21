# Plan

## Objective

Reinstate this repo as a first-class tool under `~/Work/tools/`, prove server-side **multitrack
audio recording** works live on localhost, integrate it as **Zulip's call manager**, then design its
deployment to the **ai4hu VPS**. Full negotiation record: `~/.claude/plans/prancy-brewing-sunbeam.md`.

## Checklist

- [x] De-archive → `~/Work/tools/ffmpeg-multitrack-recorder`, git remote intact
- [x] Apply dev-context (`.ruler` synced, `CLAUDE.md`/`AGENTS.md` regenerated)
- [x] Establish L4 docs
- [x] Add `justfile` (up/down/test/health/record/mixdown/merge)
- [x] **Phase 1** — Proved audio multitrack on **pinned** `stable-10590`: fresh MKA with 2 Opus tracks (`ffprobe` == participants); E2E audio suite 34/34 (1 batch-run fail was self-interference, green in isolation) 🔴 **at checkpoint**
- [ ] **Phase 1B** — Re-validate on **latest** Jitsi + deps; adopt latest or record newest-working ceiling 🔴 checkpoint
- [ ] **Phase 2** — Point Zulip video-call provider at our Jitsi; record a Zulip-started call on localhost 🔴 checkpoint
- [ ] **Phase 3** — ai4hu-vps feasibility (is VPS hardware suitable/necessary?) + deploy design; **research only** 🔴 hard gate

## Success criteria

A brand-new `recordings/<ts>_<room>_<uuid>/recording.mka` with one Opus track per participant
(verified by `ffprobe`) + matching `metadata.json`, produced both by the E2E suite and by a
Zulip-initiated call — on the newest Jitsi version that still works.
