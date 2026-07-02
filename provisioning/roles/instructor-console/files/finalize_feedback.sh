#!/usr/bin/env bash
#
# PUC2-Sub Case 2a — Gate 2 one-shot: SCORE -> DELIVER -> PUBLISH.
#
# Runs on the instructor console. Chains the exact commands behind the
# SCORE_CAMPAIGN / DELIVER_FEEDBACK / PUBLISH_FEEDBACK shortcuts and adds
# automatic campaign-id resolution so the instructor does not have to look it up.
#
# Usage:
#   finalize_feedback.sh [campaign_id]
#     * with an id  -> uses it verbatim.
#     * without id  -> resolves the most recent campaign (highest id) from the
#                      GoPhish API, using the persisted key on reporting-workspace.
#
# Idempotent / re-runnable: scoring upserts, delivery regenerates, publish
# overwrites the feedback pages.
set -euo pipefail

GOPHISH_HOST="http://phishing-simulator.internal:3333"

log() { printf '[*] %s\n' "$*"; }
err() { printf '[!] %s\n' "$*" >&2; }

# Resolve the campaign id from GoPhish. The API key is read on reporting-workspace
# (it holds /opt/rep-scoring/gophish.env and can reach GoPhish), so the instructor
# console never needs the key itself. Echoes "<count> <max_id>".
resolve_campaign() {
    local json
    json="$(ssh reporting-workspace \
        "set -a; . /opt/rep-scoring/gophish.env; \
         curl -fsS -H \"Authorization: \$GOPHISH_API_KEY\" ${GOPHISH_HOST}/api/campaigns/")"
    printf '%s' "$json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
ids = sorted(c["id"] for c in data) if isinstance(data, list) else []
print(len(ids), ids[-1] if ids else 0)
'
}

CID="${1:-}"
if [ -z "$CID" ]; then
    log "No campaign id given; resolving the most recent campaign from GoPhish ..."
    if ! out="$(resolve_campaign)"; then
        err "Could not query GoPhish campaigns via reporting-workspace. Is GoPhish up?"
        exit 1
    fi
    count="${out%% *}"
    CID="${out##* }"
    if [ "$count" -eq 0 ]; then
        err "No campaigns exist in GoPhish. Launch one first with LAUNCH_CAMPAIGN."
        exit 1
    fi
    if [ "$count" -gt 1 ]; then
        err "Found $count campaigns and no id was given; using the most recent (id $CID)."
    fi
    log "Using campaign id $CID (most recent)."
else
    log "Using campaign id $CID (provided)."
fi

log "SCORE  : scoring campaign $CID on reporting-workspace ..."
ssh -t reporting-workspace "set -a; . /opt/rep-scoring/gophish.env; python3 /opt/rep-scoring/score_campaign.py $CID"

log "DELIVER: generating and delivering feedback for campaign $CID ..."
ssh -t reporting-workspace "python3 /opt/rep-scoring/deliver_feedback.py $CID"

log "PUBLISH: publishing feedback pages to the LMS ..."
ssh lms.internal 'mkdir -p /srv/lms/feedback'
scp -3 -o StrictHostKeyChecking=no reporting-workspace:/tmp/rep-feedback/*.html lms.internal:/srv/lms/feedback/

printf '\n[+] Campaign %s scored, feedback delivered, pages published at http://lms.internal:8080/feedback/\n' "$CID"
