# Shared helpers for verify-psych-cert-gen. Load this file from the entry script.
# Read run.env line by line in harness.py. Never chmod a directory the caller passed in.

if [ -z "${BIN_DIR:-}" ]; then
  BIN_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
fi
HARNESS="$BIN_DIR/harness.py"

discover_repo() {
  local dir
  dir=$BIN_DIR
  while [ "$dir" != "/" ]; do
    if [ -f "$dir/certgen.py" ] && [ -f "$dir/package.json" ]; then
      printf '%s' "$dir"
      return 0
    fi
    dir=$(dirname -- "$dir")
  done
  return 1
}

require_platform_first() {
  python3 "$HARNESS" platform >/dev/null || return 1
}

load_env_args() {
  local blob line
  blob=$(python3 "$HARNESS" child-env "$STATE_DIR") || return 1
  ENV_ARGS=()
  while IFS= read -r line; do
    if [ -n "$line" ]; then
      ENV_ARGS[${#ENV_ARGS[@]}]=$line
    fi
  done <<EOF
$blob
EOF
  if [ "${#ENV_ARGS[@]}" -eq 0 ]; then
    return 1
  fi
}

record_before_state() {
  local extra
  extra=$(python3 "$HARNESS" prefs-extra) || return 1
  if [ -n "$extra" ]; then
    python3 "$HARNESS" record-before "$STATE_DIR/before-manifest" "$extra" || return 1
  else
    python3 "$HARNESS" record-before "$STATE_DIR/before-manifest" || return 1
  fi
}

compare_before_state() {
  local extra
  extra=$(python3 "$HARNESS" prefs-extra) || return 1
  if [ -n "$extra" ]; then
    python3 "$HARNESS" compare-before "$STATE_DIR/before-manifest" "$extra" || return 1
  else
    python3 "$HARNESS" compare-before "$STATE_DIR/before-manifest" || return 1
  fi
}

create_run() {
  local evid base pointer
  require_platform_first || return 1
  RUN_ID=$(python3 "$HARNESS" make-run-id) || return 1
  REG=$(python3 "$HARNESS" registry) || return 1
  umask 077
  STATE_DIR=$(mktemp -d "$REG/state.XXXXXX") || return 1
  python3 "$HARNESS" tighten-created "$STATE_DIR" || return 1
  evid=$(mktemp -d "$STATE_DIR/evidence.XXXXXX") || return 1
  python3 "$HARNESS" init-evidence "$STATE_DIR" "$evid" || return 1
  mkdir -m 700 \
    "$STATE_DIR/home" \
    "$STATE_DIR/tmp" \
    "$STATE_DIR/output" \
    "$STATE_DIR/logs" \
    "$STATE_DIR/pass" || return 1
  python3 "$HARNESS" write-state "$STATE_DIR/run.env" RUN_ID "$RUN_ID" || return 1
  python3 "$HARNESS" write-state "$STATE_DIR/run.env" OWNER_UID "$(id -u)" || return 1
  base=$(basename -- "$STATE_DIR") || return 1
  pointer="$REG/id-$RUN_ID"
  printf '%s\n' "$base" >"$pointer" || return 1
  chmod 600 "$pointer" || return 1
}

use_id() {
  RUN_ID=$1
  STATE_DIR=$(python3 "$HARNESS" resolve-run "$RUN_ID") || return 1
  REPO=$(discover_repo) || return 1
}

ready_never() {
  return 1
}

ready_api() {
  local pid i
  pid=$1
  i=0
  while [ "$i" -lt 80 ]; do
    if python3 "$HARNESS" health-ok "http://127.0.0.1:8008/health" "$pid" 2>/dev/null; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    i=$((i + 1))
    sleep 0.25
  done
  return 1
}

ready_ui() {
  local pid i
  pid=$1
  i=0
  while [ "$i" -lt 240 ]; do
    if python3 "$HARNESS" http-exact "http://127.0.0.1:1420/" "/" 2>/dev/null; then
      kill -0 "$pid" 2>/dev/null || return 1
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    i=$((i + 1))
    sleep 0.25
  done
  return 1
}

ready_browser() {
  local pid i
  pid=$1
  i=0
  while [ "$i" -lt 100 ]; do
    if [ -S "$STATE_DIR/browser.sock" ]; then
      kill -0 "$pid" 2>/dev/null || return 1
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    i=$((i + 1))
    sleep 0.2
  done
  return 1
}

kill_failed_launch() {
  local pid i
  pid=$1
  kill "$pid" 2>/dev/null || true
  python3 "$HARNESS" signal-launch-group "$pid" || true
  i=0
  while [ "$i" -lt 25 ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    i=$((i + 1))
    sleep 0.1
  done
  kill -KILL "$pid" 2>/dev/null || true
  return 0
}

start_in_repo() {
  local log ready back
  log=$1
  ready=$2
  shift 2
  if [ "${1:-}" != "--" ]; then
    return 2
  fi
  shift
  if [ "$#" -lt 1 ]; then
    return 2
  fi
  if [ "${#ENV_ARGS[@]}" -eq 0 ]; then
    return 1
  fi
  back=$(pwd) || return 1
  cd "$REPO" || return 1
  env -i "${ENV_ARGS[@]}" "$@" >>"$log" 2>&1 &
  SUPERVISE_PID=$!
  cd "$back" || return 1
  if ! "$ready" "$SUPERVISE_PID"; then
    kill_failed_launch "$SUPERVISE_PID"
    return 1
  fi
  return 0
}

supervise_start() {
  local log ready
  log=$1
  ready=$2
  shift 2
  if [ "${1:-}" != "--" ]; then
    return 2
  fi
  shift
  if [ "$#" -lt 1 ]; then
    return 2
  fi
  "$@" >>"$log" 2>&1 &
  SUPERVISE_PID=$!
  if ! "$ready" "$SUPERVISE_PID"; then
    kill_failed_launch "$SUPERVISE_PID"
    return 1
  fi
  return 0
}

stop_recorded_processes() {
  python3 "$HARNESS" confirm-all "$STATE_DIR" || return 1
  python3 "$HARNESS" signal-confirmed "$STATE_DIR" || return 1
}

empty_array_ok() {
  local empty
  empty=()
  # shellcheck disable=SC2086
  printf '%s' ${empty[@]+"${empty[@]}"}
  return 0
}

step() {
  python3 "$HARNESS" append-evidence "$STATE_DIR" "drive.log" <<<"$*" || return 1
  python3 "$HARNESS" rpc "$STATE_DIR/browser.sock" "$@" || return 1
}

shot() {
  local width height name
  width=$1
  height=$2
  name=$3
  python3 "$HARNESS" rpc "$STATE_DIR/browser.sock" screenshot "$width" "$height" "$STATE_DIR/tmp/$name" || return 1
  python3 "$HARNESS" write-evidence "$STATE_DIR" "$name" <"$STATE_DIR/tmp/$name" || return 1
  rm -f "$STATE_DIR/tmp/$name"
  python3 "$HARNESS" rpc "$STATE_DIR/browser.sock" screenshot "$width" "$height" "$STATE_DIR/tmp/full-$name" full || return 1
  python3 "$HARNESS" write-evidence "$STATE_DIR" "full-$name" <"$STATE_DIR/tmp/full-$name" || return 1
  rm -f "$STATE_DIR/tmp/full-$name"
}

aria_shot() {
  local name
  name=$1
  python3 "$HARNESS" rpc "$STATE_DIR/browser.sock" aria "$STATE_DIR/tmp/$name" || return 1
  python3 "$HARNESS" write-evidence "$STATE_DIR" "$name" <"$STATE_DIR/tmp/$name" || return 1
  rm -f "$STATE_DIR/tmp/$name"
}

scan_side_effects() {
  local raw scheme target
  raw=$(python3 "$HARNESS" rpc "$STATE_DIR/browser.sock" scan-side-effects) || return 1
  if [ -z "$raw" ]; then
    python3 "$HARNESS" append-evidence "$STATE_DIR" "side-effects.txt" <<<"none" || return 1
    return 0
  fi
  printf '%s\n' "$raw" | while IFS= read -r target; do
    [ -n "$target" ] || continue
    scheme=${target%%:*}
    python3 "$HARNESS" side-effect "$STATE_DIR/tmp/side-effects.log" "$scheme" "$target" || exit 1
  done
  echo "refusing page links with a real-world scheme" >&2
  return 1
}

cmd_launch() {
  local uv bun node
  require_platform_first || return 1
  REPO=$(discover_repo) || return 1
  python3 "$HARNESS" port-free 8008 || return 1
  python3 "$HARNESS" port-free 1420 || return 1
  if [ ! -x "$REPO/.venv/bin/python" ]; then
    echo "missing $REPO/.venv/bin/python (run uv sync in the repo)" >&2
    return 1
  fi
  uv=$(python3 "$HARNESS" find-exe uv) || return 1
  bun=$(python3 "$HARNESS" find-exe bun) || return 1
  node=$(python3 "$HARNESS" find-exe node) || return 1
  create_run || return 1
  record_before_state || return 1
  load_env_args || return 1
  if ! start_in_repo "$STATE_DIR/logs/api.log" ready_api -- \
    PSYCH_CERT_PORT=8008 \
    python3 "$HARNESS" exec-setsid -- \
    "$REPO/.venv/bin/python" src/backends/main.py
  then
    echo "API failed to become ready; run id $RUN_ID" >&2
    return 1
  fi
  python3 "$HARNESS" write-identity "$STATE_DIR/run.env" API "$SUPERVISE_PID" || return 1
  if ! start_in_repo "$STATE_DIR/logs/ui.log" ready_ui -- \
    VITE_E2E=1 \
    python3 "$HARNESS" exec-setsid -- \
    "$bun" run dev -- --host 127.0.0.1 --port 1420
  then
    stop_recorded_processes || true
    echo "UI failed to become ready; run id $RUN_ID" >&2
    echo "recovery: $BIN_DIR/verify-psych-cert-gen cleanup --id $RUN_ID --abandon" >&2
    return 1
  fi
  python3 "$HARNESS" write-identity "$STATE_DIR/run.env" UI "$SUPERVISE_PID" || return 1
  if ! start_in_repo "$STATE_DIR/logs/browser.log" ready_browser -- \
    PSYCH_CERT_STATE="$STATE_DIR" \
    PSYCH_CERT_REPO="$REPO" \
    python3 "$HARNESS" exec-setsid -- \
    "$node" "$BIN_DIR/browser-server.mjs"
  then
    stop_recorded_processes || true
    echo "browser failed to become ready; run id $RUN_ID" >&2
    echo "recovery: $BIN_DIR/verify-psych-cert-gen cleanup --id $RUN_ID --abandon" >&2
    return 1
  fi
  python3 "$HARNESS" write-identity "$STATE_DIR/run.env" BROWSER "$SUPERVISE_PID" || return 1
  if ! step goto / || ! step wait-heading "Training Metadata"; then
    stop_recorded_processes || true
    echo "wizard heading did not appear; run id $RUN_ID" >&2
    echo "recovery: $BIN_DIR/verify-psych-cert-gen cleanup --id $RUN_ID --abandon" >&2
    return 1
  fi
  echo "run_id=$RUN_ID"
  echo "evidence=$(python3 "$HARNESS" evidence-dir "$STATE_DIR")"
  echo "ui=http://127.0.0.1:1420/"
  echo "api=http://127.0.0.1:8008/health"
  echo "uv=$uv"
}

cmd_doctor() {
  local id
  id=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --id)
        id=${2:-}
        shift 2
        ;;
      *)
        echo "usage: doctor --id RUN_ID" >&2
        return 2
        ;;
    esac
  done
  if [ -z "$id" ]; then
    echo "doctor requires --id" >&2
    return 2
  fi
  use_id "$id" || return 1
  python3 "$HARNESS" doctor "$STATE_DIR" "$REPO" || return 1
}

cmd_cleanup() {
  local id abandon prefs_bad
  id=""
  abandon=0
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --id)
        id=${2:-}
        shift 2
        ;;
      --abandon)
        abandon=1
        shift
        ;;
      *)
        echo "usage: cleanup --id RUN_ID [--abandon]" >&2
        return 2
        ;;
    esac
  done
  if [ -z "$id" ]; then
    echo "cleanup requires --id and does not guess one" >&2
    return 2
  fi
  use_id "$id" || return 1
  prefs_bad=0
  if ! compare_before_state; then
    prefs_bad=1
  fi
  if [ "$abandon" -eq 1 ]; then
    if ! python3 "$HARNESS" all-dead "$STATE_DIR"; then
      echo "a recorded process is still running; state kept" >&2
      echo "recovery: $BIN_DIR/verify-psych-cert-gen cleanup --id $id --abandon" >&2
      return 1
    fi
    if [ "$prefs_bad" -eq 1 ]; then
      echo "prefs changed; state kept" >&2
      return 1
    fi
    python3 "$HARNESS" wipe-scratch "$STATE_DIR" || return 1
    echo "abandoned"
    echo "evidence=$(python3 "$HARNESS" evidence-dir "$STATE_DIR")"
    return 0
  fi
  if ! python3 "$HARNESS" confirm-all "$STATE_DIR"; then
    echo "identity not confirmed; state kept" >&2
    echo "recovery: $BIN_DIR/verify-psych-cert-gen cleanup --id $id --abandon" >&2
    return 1
  fi
  if [ "$prefs_bad" -eq 1 ]; then
    python3 "$HARNESS" signal-confirmed "$STATE_DIR" || return 1
    echo "prefs changed; processes stopped; state kept" >&2
    return 1
  fi
  python3 "$HARNESS" signal-confirmed "$STATE_DIR" || return 1
  python3 "$HARNESS" wipe-scratch "$STATE_DIR" || return 1
  echo "cleaned"
  echo "evidence=$(python3 "$HARNESS" evidence-dir "$STATE_DIR")"
}

cmd_run() {
  if [ "${1:-}" != "--" ]; then
    echo "usage: run -- command" >&2
    return 2
  fi
  shift
  if [ "$#" -eq 0 ]; then
    return 2
  fi
  "$@"
}

cmd_browser() {
  local id
  id=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --id)
        id=${2:-}
        shift 2
        ;;
      --)
        shift
        break
        ;;
      *)
        break
        ;;
    esac
  done
  if [ -z "$id" ]; then
    echo "browser requires --id" >&2
    return 2
  fi
  use_id "$id" || return 1
  python3 "$HARNESS" rpc "$STATE_DIR/browser.sock" "$@" || return 1
}

drive_generate() {
  local zoom qual epoch zip
  zoom="$REPO/tests/fixtures/pilot_zoom.xlsx"
  qual="$REPO/tests/fixtures/pilot_qualtrics.xlsx"
  epoch=$(python3 "$HARNESS" now-ns) || return 1
  step goto / || return 1
  step expect-url / || return 1
  step wait-heading "Training Metadata" || return 1
  scan_side_effects || return 1
  step fill-label "Training Title" "Ethics and Practice in School-Based Mental Health" || return 1
  step fill-label "Date" "2026-10-06" || return 1
  step fill-label "Instructor Name" "Dr. Amira Solano" || return 1
  step fill-label "CE Credits" "3" || return 1
  step check-role checkbox "APA" || return 1
  step check-role checkbox "NASP" || return 1
  step check-role checkbox "NY" || return 1
  step check-role checkbox "NBCC" || return 1
  step fill-label "Start Time" "09:00" || return 1
  step fill-label "End Time" "12:00" || return 1
  shot 1280 900 metadata-desktop.png || return 1
  step click-role button "Next" || return 1
  step wait-heading "Step 2: Upload Files" || return 1
  step seed-paths "$zoom" "$qual" "$STATE_DIR/output" || return 1
  step click-role button "Select Zoom Report" || return 1
  step click-role button "Select Qualtrics Survey" || return 1
  step click-role button "Parse Files" || return 1
  step expect-text "14 participants found, 14 CE requests found" || return 1
  shot 1280 900 upload-desktop.png || return 1
  step click-role button "Next" || return 1
  step wait-heading "Review Name Matches" || return 1
  step expect-text "11 matched" || return 1
  step expect-text "1 ambiguous" || return 1
  step expect-text "1 not found" || return 1
  step expect-host "Morgan Hale" || return 1
  shot 1280 900 review-desktop.png || return 1
  step click-role button "Next" || return 1
  step wait-heading "Generate Certificates" || return 1
  step expect-text "8 eligible certificates ready to generate." || return 1
  step click-role button "Preview Certificate" || return 1
  step wait-canvas || return 1
  step click-role button "Choose output folder" || return 1
  step expect-output "output" || return 1
  step click-role button "Generate All Certificates" || return 1
  step expect-text "Generated Certificates (8)" 120 || return 1
  step expect-text "Avery Chen" || return 1
  step expect-text "Riley Okonkwo" || return 1
  shot 1280 900 generate-desktop.png || return 1
  shot 768 1024 generate-tablet.png || return 1
  shot 375 812 generate-mobile.png || return 1
  aria_shot generate.aria.txt || return 1
  python3 "$HARNESS" prove-pdfs "$STATE_DIR/output" "$epoch" "$STATE_DIR" || return 1
  step download-zip "$STATE_DIR/output/certificates.zip" || return 1
  zip="$STATE_DIR/output/certificates.zip"
  python3 - "$zip" <<'PY' || return 1
import sys
import zipfile
archive = zipfile.ZipFile(sys.argv[1])
names = [name for name in archive.namelist() if name.endswith(".pdf")]
if len(names) != 8:
    sys.stderr.write(f"zip pdf count {len(names)}\n")
    raise SystemExit(1)
PY
  scan_side_effects || return 1
}

drive_metadata() {
  step goto / || return 1
  step wait-heading "Training Metadata" || return 1
  step fill-label "Training Title" "Ethics and Practice in School-Based Mental Health" || return 1
  step fill-label "Date" "2026-10-06" || return 1
  step fill-label "Instructor Name" "Dr. Amira Solano" || return 1
  step fill-label "CE Credits" "3" || return 1
  step check-role checkbox "APA" || return 1
  step fill-label "Start Time" "09:00" || return 1
  step fill-label "End Time" "12:00" || return 1
  step expect-enabled button "Next" || return 1
}

drive_upload() {
  drive_metadata || return 1
  step check-role checkbox "NASP" || return 1
  step check-role checkbox "NY" || return 1
  step check-role checkbox "NBCC" || return 1
  step click-role button "Next" || return 1
  step wait-heading "Step 2: Upload Files" || return 1
  step seed-paths \
    "$REPO/tests/fixtures/pilot_zoom.xlsx" \
    "$REPO/tests/fixtures/pilot_qualtrics.xlsx" \
    "$STATE_DIR/output" || return 1
  step click-role button "Select Zoom Report" || return 1
  step click-role button "Select Qualtrics Survey" || return 1
  step click-role button "Parse Files" || return 1
  step expect-text "14 participants found, 14 CE requests found" || return 1
}

drive_review() {
  drive_upload || return 1
  step click-role button "Next" || return 1
  step wait-heading "Review Name Matches" || return 1
  step expect-text "11 matched" || return 1
  step expect-host "Morgan Hale" || return 1
}

drive_cli() {
  local out
  out="$STATE_DIR/output/cli"
  mkdir -m 700 "$out" || return 1
  load_env_args || return 1
  (
    cd "$REPO" || exit 1
    env -i "${ENV_ARGS[@]}" \
      "$REPO/.venv/bin/python" "$REPO/certgen.py" \
      --title "Ethics and Practice in School-Based Mental Health" \
      --date "2026-10-06" \
      --instructor "Dr. Amira Solano" \
      --ce-credits 3 \
      --ce-types "APA,NASP,NY,NBCC" \
      --start-time "09:00" \
      --end-time "12:00" \
      --zoom-report "$REPO/tests/fixtures/pilot_zoom.xlsx" \
      --qualtrics-report "$REPO/tests/fixtures/pilot_qualtrics.xlsx" \
      --output-dir "$out"
  ) || return 1
  python3 "$HARNESS" prove-pdfs "$out" 0 "$STATE_DIR" || return 1
}

cmd_drive() {
  local id feature
  id=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --id)
        id=${2:-}
        shift 2
        ;;
      *)
        break
        ;;
    esac
  done
  feature=${1:-}
  if [ -z "$id" ] || [ -z "$feature" ]; then
    echo "usage: drive --id RUN_ID FEATURE" >&2
    return 2
  fi
  use_id "$id" || return 1
  case "$feature" in
    generate-certificates)
      drive_generate
      ;;
    training-metadata)
      drive_metadata
      ;;
    upload-files)
      drive_upload
      ;;
    review-matches)
      drive_review
      ;;
    cli-batch)
      drive_cli
      ;;
    *)
      echo "unknown feature: $feature" >&2
      return 2
      ;;
  esac
}

cmd_copy_sandbox() {
  python3 "$HARNESS" copy-tracked "$1" "$2" || return 1
}
