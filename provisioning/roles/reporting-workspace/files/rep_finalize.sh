#!/usr/bin/env bash
#
# PUC2-Sub Case 2a — Gate 2 auto-finalize (unattended).
#
# Runs ON reporting-workspace from a systemd timer (rep-finalize.timer). It is
# the automated equivalent of the instructor-console FINALIZE_FEEDBACK alias:
#   1. resolve the most recent GoPhish campaign id (via the GoPhish API);
#   2. score_campaign.py  <id>  -> upserts trainee scores into PostgreSQL;
#   3. deliver_feedback.py <id> -> regenerates feedback emails + HTML pages;
#   4. publish the *.html pages to the LMS (lms.internal:/srv/lms/feedback/).
#
# Idempotent and safe to re-run every few minutes:
#   * scoring upserts, delivery regenerates, publish overwrites in place.
#   * no campaign yet           -> log "no campaign yet" + EXIT 0 (timer retries).
#   * transient failure (GoPhish/LMS/SMTP down) -> log + EXIT 0 (timer stays up).
#   * only a clear config error -> EXIT 1.
#
# The GoPhish API key is injected by the systemd EnvironmentFile
# (/opt/rep-scoring/gophish.env, GOPHISH_API_KEY=...). When run by hand, source
# that file first (it is mode 0600, so that needs root).
#
# SSH/PUBLISH ACCESS (see provisioning/playbook.yml, play "Authorize
# reporting-workspace SSH key on LMS ..."): publishing runs as the local
# ${reporting_workspace_publish_user} (default: ubuntu) using its
# ~/.ssh/id_ed25519 key, which is authorised in the LMS deploy user's
# authorized_keys. Target: ${LMS_SSH_USER}@${LMS_HOST}:${LMS_FEEDBACK_DIR}.
# This mirrors the manual publish_feedback path and does not disturb it.

set -uo pipefail

SCORING_DIR="${SCORING_DIR:-/opt/rep-scoring}"
OUTPUT_DIR="${OUTPUT_DIR:-/tmp/rep-feedback}"
GOPHISH_HOST="${GOPHISH_HOST:-http://phishing-simulator.internal:3333}"
GOPHISH_ENV="${GOPHISH_ENV:-${SCORING_DIR}/gophish.env}"
LMS_HOST="${LMS_HOST:-lms.internal}"
LMS_SSH_USER="${LMS_SSH_USER:-ubuntu}"
LMS_FEEDBACK_DIR="${LMS_FEEDBACK_DIR:-/srv/lms/feedback}"
SSH_OPTS=(-o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=10)

log() { printf '[rep-finalize] %s\n' "$*"; }

# deliver_feedback.py writes the per-trainee pages here.
export OUTPUT_DIR

# The GoPhish API key normally arrives via the systemd EnvironmentFile. When it
# is missing (manual run) fall back to sourcing the env file if it is readable.
if [ -z "${GOPHISH_API_KEY:-}" ] && [ -r "${GOPHISH_ENV}" ]; then
    # shellcheck disable=SC1090
    set -a; . "${GOPHISH_ENV}"; set +a
fi

if [ -z "${GOPHISH_API_KEY:-}" ]; then
    log "CONFIG ERROR: GOPHISH_API_KEY is unset and ${GOPHISH_ENV} is not readable."
    exit 1
fi
export GOPHISH_API_KEY GOPHISH_HOST

# 1) Resolve the most recent campaign id. A transient API failure must not kill
#    the timer, so any problem here => log + EXIT 0.
campaigns_json="$(curl -fsS -H "Authorization: ${GOPHISH_API_KEY}" \
    "${GOPHISH_HOST}/api/campaigns/" 2>/dev/null)" || {
    log "GoPhish not reachable at ${GOPHISH_HOST} (transient); will retry next tick."
    exit 0
}

resolved="$(printf '%s' "${campaigns_json}" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print(0, 0); sys.exit(0)
ids = sorted(c["id"] for c in data) if isinstance(data, list) else []
print(len(ids), ids[-1] if ids else 0)
')"
count="${resolved%% *}"
cid="${resolved##* }"

if [ "${count:-0}" -eq 0 ]; then
    log "no campaign yet; nothing to finalize."
    exit 0
fi
[ "${count}" -gt 1 ] && log "found ${count} campaigns; using the most recent (id ${cid})."
log "finalizing campaign id ${cid}."

# 2) Score (upsert into PostgreSQL).
if ! python3 "${SCORING_DIR}/score_campaign.py" "${cid}"; then
    log "score_campaign.py failed for campaign ${cid} (transient); will retry next tick."
    exit 0
fi

# 3) Deliver feedback (regenerate emails + HTML pages into OUTPUT_DIR).
if ! python3 "${SCORING_DIR}/deliver_feedback.py" "${cid}"; then
    log "deliver_feedback.py failed for campaign ${cid} (transient); will retry next tick."
    exit 0
fi

# 4) Publish the feedback pages to the LMS (overwrites in place).
shopt -s nullglob
pages=("${OUTPUT_DIR}"/*.html)
shopt -u nullglob
if [ "${#pages[@]}" -eq 0 ]; then
    log "no feedback pages in ${OUTPUT_DIR} to publish; will retry next tick."
    exit 0
fi

if ! ssh "${SSH_OPTS[@]}" "${LMS_SSH_USER}@${LMS_HOST}" "mkdir -p '${LMS_FEEDBACK_DIR}'"; then
    log "cannot reach LMS ${LMS_SSH_USER}@${LMS_HOST} (transient); will retry next tick."
    exit 0
fi
if ! scp "${SSH_OPTS[@]}" "${pages[@]}" "${LMS_SSH_USER}@${LMS_HOST}:${LMS_FEEDBACK_DIR}/"; then
    log "publish to LMS failed (transient); will retry next tick."
    exit 0
fi

log "campaign ${cid} scored, feedback delivered, ${#pages[@]} page(s) published to http://${LMS_HOST}:8080/feedback/"
exit 0
