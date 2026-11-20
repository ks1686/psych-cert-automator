#!/usr/bin/env bash
# Prove the verification helper guards. Run this from any directory.
set -euo pipefail
BIN_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib.sh
. "$BIN_DIR/lib.sh"
VERIFY="$BIN_DIR/verify-psych-cert-gen"
REPO=$(discover_repo) || {
  echo "repo not found" >&2
  exit 1
}

FAIL=0
SCRATCH=$(mktemp -d)
export PSYCH_CERT_VERIFY_RUNTIME="$SCRATCH/runtime"
mkdir -m 700 "$PSYCH_CERT_VERIFY_RUNTIME"
PIDS="$SCRATCH/pids"
: >"$PIDS"
REPO_BEFORE=$(git -C "$REPO" status --porcelain)
TMP_BEFORE=$(find /tmp /private/tmp -maxdepth 3 \( -name 'psych-cert-verify-uid-*' -o -name 'state.*' \) -user "$(id -u)" 2>/dev/null | sort || true)

finish() {
  trap - EXIT
  local pid tmp_after
  local status=$1
  if [ -f "$PIDS" ]; then
    while IFS= read -r pid; do
      if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null || true
      fi
    done <"$PIDS"
  fi
  if [ -d "$SCRATCH" ]; then
    chmod -R u+w "$SCRATCH" 2>/dev/null || true
    rm -rf "$SCRATCH"
  fi
  tmp_after=$(find /tmp /private/tmp -maxdepth 3 \( -name 'psych-cert-verify-uid-*' -o -name 'state.*' \) -user "$(id -u)" 2>/dev/null | sort || true)
  if [ "$tmp_after" != "$TMP_BEFORE" ]; then
    printf 'leftover temp dirs:\n%s\n' "$tmp_after" >&2
    status=1
  fi
  exit "$status"
}
trap 'finish $?' EXIT

note_pid() {
  printf '%s\n' "$1" >>"$PIDS"
}

check() {
  local name rc
  name=$1
  if [ -z "$name" ]; then
    printf 'FAIL empty-check\n' >&2
    FAIL=1
    return
  fi
  set +e
  "$name"
  rc=$?
  set -e
  if [ "$rc" -eq 0 ]; then
    printf 'PASS %s\n' "$name"
  else
    printf 'FAIL %s\n' "$name" >&2
    FAIL=1
  fi
}

assert_fail() {
  set +e
  "$@"
  local rc=$?
  set -e
  if [ "$rc" -eq 0 ]; then
    return 1
  fi
  return 0
}

last_line() {
  printf '%s\n' "$1" | awk 'NF { line=$0 } END { print line }'
}

check_platform_before_dirs() {
  local empty count
  empty=$(mktemp -d "$SCRATCH/platform.XXXXXX")
  assert_fail env PSYCH_CERT_VERIFY_ASSUME_UNAME=Haiku TMPDIR="$empty" "$VERIFY" launch
  count=$(find "$empty" -mindepth 1 | wc -l | tr -d ' ')
  [ "$count" -eq 0 ]
  assert_fail env PSYCH_CERT_VERIFY_ASSUME_UNAME=Haiku python3 "$HARNESS" registry
}

check_private_dirs() {
  local caller before after state evid proof
  caller=$(mktemp -d "$SCRATCH/caller.XXXXXX")
  chmod 707 "$caller"
  before=$(python3 "$HARNESS" mode "$caller")
  assert_fail python3 "$HARNESS" refuse-caller "$caller"
  after=$(python3 "$HARNESS" mode "$caller")
  [ "$before" = "$after" ]
  [ "$before" = "0707" ]
  before=$(python3 "$HARNESS" mode /usr)
  assert_fail python3 "$HARNESS" refuse-caller /usr
  after=$(python3 "$HARNESS" mode /usr)
  [ "$before" = "$after" ]
  caller=$(mktemp -d "$SCRATCH/caller750.XXXXXX")
  chmod 750 "$caller"
  before=$(python3 "$HARNESS" mode "$caller")
  PSYCH_CERT_VERIFY_RUNTIME="$caller" python3 "$HARNESS" registry >/dev/null
  after=$(python3 "$HARNESS" mode "$caller")
  [ "$before" = "$after" ]
  create_run
  python3 "$HARNESS" assert-private "$STATE_DIR"
  evid=$(python3 "$HARNESS" evidence-dir "$STATE_DIR")
  python3 "$HARNESS" assert-private "$evid"
  printf 'proof\n' | python3 "$HARNESS" write-evidence "$STATE_DIR" proof.txt
  proof=$(python3 "$HARNESS" mode "$evid/proof.txt")
  [ "$proof" = "0600" ]
}

check_run_env_literal() {
  local value
  create_run
  python3 "$HARNESS" write-state "$STATE_DIR/run.env" EVIL '$(touch pwned); rm -rf /'
  value=$(python3 "$HARNESS" read-state "$STATE_DIR/run.env" EVIL) || return 1
  [ "$value" = '$(touch pwned); rm -rf /' ]
  [ ! -e "$SCRATCH/pwned" ]
  [ ! -e pwned ]
}

check_home_not_from_state() {
  local out
  create_run
  python3 "$HARNESS" write-state "$STATE_DIR/run.env" HOME /tmp/evil-home
  out=$(python3 "$HARNESS" child-env "$STATE_DIR") || return 1
  printf '%s\n' "$out" | grep -x "HOME=$STATE_DIR/home" >/dev/null
  printf '%s\n' "$out" | grep -x 'GOTELEMETRY=off' >/dev/null
}

check_tool_path_not_from_state() {
  local found out
  create_run
  python3 "$HARNESS" write-state "$STATE_DIR/run.env" UV /tmp/evil-uv
  found=$(python3 "$HARNESS" find-exe uv) || return 1
  [ "$found" != "/tmp/evil-uv" ]
  [ -x "$found" ]
  out=$(GOTELEMETRY=on GOMODCACHE="$SCRATCH/gomod" PLAYWRIGHT_BROWSERS_PATH="$SCRATCH/pw" \
    python3 "$HARNESS" child-env "$STATE_DIR") || return 1
  printf '%s\n' "$out" | grep -x 'GOTELEMETRY=off' >/dev/null
  printf '%s\n' "$out" | grep -x "GOMODCACHE=$SCRATCH/gomod" >/dev/null
  printf '%s\n' "$out" | grep -x "PLAYWRIGHT_BROWSERS_PATH=$SCRATCH/pw" >/dev/null
  printf '%s\n' "$out" | grep '^NPM_CONFIG_CACHE=.' >/dev/null
}

expect_rc() {
  local want rc
  want=$1
  shift
  set +e
  "$@" >/dev/null 2>&1
  rc=$?
  set -e
  [ "$rc" -eq "$want" ]
}

check_run_ids() {
  local id other
  expect_rc 2 python3 "$HARNESS" valid-id .
  expect_rc 2 python3 "$HARNESS" valid-id ..
  expect_rc 2 python3 "$HARNESS" valid-id ../x
  expect_rc 2 python3 "$HARNESS" valid-id 'a/b'
  expect_rc 2 python3 "$HARNESS" valid-id 'has space'
  expect_rc 2 python3 "$HARNESS" valid-id ''
  python3 "$HARNESS" valid-id 'ok-id_1'
  id=$(python3 "$HARNESS" make-run-id) || return 1
  other=$(python3 "$HARNESS" make-run-id) || return 1
  [ "$id" != "$other" ]
  python3 "$HARNESS" valid-id "$id"
  expect_rc 2 "$VERIFY" doctor --id .
  expect_rc 2 "$VERIFY" doctor --id ..
  expect_rc 2 "$VERIFY" cleanup --id ../x
  expect_rc 2 "$VERIFY" drive --id . generate-certificates
}

check_cleanup_requires_id() {
  local rc out
  create_run
  set +e
  out=$("$VERIFY" cleanup 2>&1)
  rc=$?
  set -e
  [ "$rc" -eq 2 ]
  printf '%s\n' "$out" | grep -x cleaned >/dev/null && return 1
  [ -d "$STATE_DIR/home" ]
  return 0
}

check_failed_launch_kills() {
  local log
  log="$SCRATCH/fail-launch.log"
  assert_fail supervise_start "$log" ready_never -- python3 "$HARNESS" exec-setsid -- sleep 30
  note_pid "$SUPERVISE_PID"
  if kill -0 "$SUPERVISE_PID" 2>/dev/null; then
    return 1
  fi
  return 0
}

check_mismatch_does_not_signal() {
  local pid out rc line
  create_run
  record_before_state || return 1
  python3 "$HARNESS" exec-setsid -- sleep 60 >>"$STATE_DIR/logs/sleep.log" 2>&1 &
  pid=$!
  note_pid "$pid"
  sleep 0.3
  python3 "$HARNESS" write-identity "$STATE_DIR/run.env" API "$pid" || return 1
  python3 "$HARNESS" write-state "$STATE_DIR/run.env" API_LSTART "Wed Jan  1 00:00:00 1970" || return 1
  python3 "$HARNESS" write-state "$STATE_DIR/run.env" API_COMMAND "rm -rf /" || return 1
  set +e
  out=$("$VERIFY" cleanup --id "$RUN_ID" 2>&1)
  rc=$?
  set -e
  [ "$rc" -ne 0 ]
  line=$(last_line "$out")
  [ "$line" != "cleaned" ]
  kill -0 "$pid" 2>/dev/null || return 1
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  set +e
  out=$("$VERIFY" cleanup --id "$RUN_ID" --abandon 2>&1)
  rc=$?
  set -e
  [ "$rc" -eq 0 ]
  printf '%s\n' "$out" | grep -x abandoned >/dev/null
  printf '%s\n' "$out" | grep -x cleaned >/dev/null && return 1
  return 0
}

check_matching_cleanup() {
  local pid out evid
  create_run
  record_before_state || return 1
  printf 'kept\n' | python3 "$HARNESS" write-evidence "$STATE_DIR" kept.txt
  evid=$(python3 "$HARNESS" evidence-dir "$STATE_DIR")
  python3 "$HARNESS" exec-setsid -- sleep 60 >>"$STATE_DIR/logs/sleep.log" 2>&1 &
  pid=$!
  note_pid "$pid"
  sleep 0.3
  python3 "$HARNESS" write-identity "$STATE_DIR/run.env" API "$pid" || return 1
  out=$("$VERIFY" cleanup --id "$RUN_ID" 2>&1) || return 1
  printf '%s\n' "$out" | grep -x cleaned >/dev/null
  if kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  [ -f "$evid/kept.txt" ]
  [ ! -d "$STATE_DIR/home" ]
}

check_ps_fail_closed() {
  assert_fail python3 "$HARNESS" ps-identity 2147483646
  create_run
  python3 "$HARNESS" write-state "$STATE_DIR/run.env" API_PID 2147483646
  python3 "$HARNESS" write-state "$STATE_DIR/run.env" API_LSTART "Wed Jan  1 00:00:00 1970"
  python3 "$HARNESS" write-state "$STATE_DIR/run.env" API_COMMAND sleep
  python3 "$HARNESS" write-state "$STATE_DIR/run.env" API_UID "$(id -u)"
  assert_fail "$VERIFY" cleanup --id "$RUN_ID"
  [ -d "$STATE_DIR/home" ]
}

check_live_pgid() {
  local first second
  python3 "$HARNESS" exec-setsid -- sleep 60 >>"$SCRATCH/pg-a.log" 2>&1 &
  first=$!
  note_pid "$first"
  python3 "$HARNESS" exec-setsid -- sleep 60 >>"$SCRATCH/pg-b.log" 2>&1 &
  second=$!
  note_pid "$second"
  sleep 0.3
  printf '1\n' >"$SCRATCH/stale-pgid"
  python3 "$HARNESS" signal-launch-group "$first" || return 1
  sleep 0.2
  if kill -0 "$first" 2>/dev/null; then
    return 1
  fi
  kill -0 "$second" 2>/dev/null || return 1
  kill "$second" 2>/dev/null || true
  wait "$second" 2>/dev/null || true
}

check_utc_lstart() {
  local pid helper utc local
  python3 "$HARNESS" exec-setsid -- sleep 30 >>"$SCRATCH/utc.log" 2>&1 &
  pid=$!
  note_pid "$pid"
  sleep 0.3
  helper=$(python3 "$HARNESS" ps-identity "$pid") || return 1
  utc=$(TZ=UTC0 LC_ALL=C ps -o lstart= -p "$pid") || return 1
  local=$(TZ=EST5 LC_ALL=C ps -o lstart= -p "$pid") || return 1
  python3 -c 'import json,sys; ident=json.loads(sys.argv[1]); utc=sys.argv[2].strip(); other=sys.argv[3].strip();
assert ident["lstart"]==utc, (ident["lstart"], utc); assert utc!=other, (utc, other)' \
    "$helper" "$utc" "$local"
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

check_evidence_guards() {
  local evid
  create_run
  evid=$(python3 "$HARNESS" evidence-dir "$STATE_DIR")
  ln -s /etc/passwd "$evid/linked"
  assert_fail python3 "$HARNESS" write-evidence "$STATE_DIR" linked <<<"x"
  ln -s "$evid/missing-target" "$evid/dangling"
  assert_fail python3 "$HARNESS" write-evidence "$STATE_DIR" dangling <<<"x"
  assert_fail python3 "$HARNESS" write-evidence "$STATE_DIR" run.env <<<"x"
  assert_fail python3 "$HARNESS" write-evidence "$STATE_DIR" ../outside.txt <<<"x"
  [ -f /etc/passwd ] || [ -d /etc/passwd ]
  [ ! -e "$STATE_DIR/outside.txt" ]
}

check_path_guards() {
  local
  assert_fail python3 "$HARNESS" guard /tmp/a/../../etc/passwd /tmp
  assert_fail python3 "$HARNESS" temp-ok /tmp/../etc
  python3 "$HARNESS" temp-ok /tmp
  python3 "$HARNESS" temp-ok /private/tmp/psych-cert-verify-prefix
  printf 'inside\n' >"$SCRATCH/inside.txt"
  python3 "$HARNESS" guard "$SCRATCH/inside.txt" "$SCRATCH"
  ln -s /etc "$SCRATCH/outlink"
  assert_fail python3 "$HARNESS" guard "$SCRATCH/outlink" "$SCRATCH"
  ln -s "$SCRATCH/inside.txt" "$SCRATCH/inlink"
  assert_fail python3 "$HARNESS" guard "$SCRATCH/inlink" "$SCRATCH"
}

check_hash_unreadable() {
  local bad hidden
  bad=$(mktemp -d "$SCRATCH/hash.XXXXXX")
  mkdir "$bad/hidden"
  printf 'x\n' >"$bad/hidden/secret"
  chmod 000 "$bad/hidden"
  assert_fail python3 "$HARNESS" hash-tree "$bad"
  chmod u+rwx "$bad/hidden"
  hidden=$(mktemp -d "$SCRATCH/filemode.XXXXXX")
  printf 'x\n' >"$hidden/secret"
  chmod 000 "$hidden/secret"
  assert_fail python3 "$HARNESS" hash-tree "$hidden"
  hash_or_return() {
    local value
    value=$(python3 "$HARNESS" hash-tree "$1") || return 1
    printf '%s' "$value"
  }
  assert_fail hash_or_return "$hidden"
  chmod u+rw "$hidden/secret"
}

check_new_files() {
  local dir epoch listed
  dir=$(mktemp -d "$SCRATCH/watch.XXXXXX")
  printf 'old\n' >"$dir/old.txt"
  python3 -c 'import os,sys,time; os.utime(sys.argv[1], (time.time()-100, time.time()-100))' "$dir/old.txt"
  epoch=$(python3 "$HARNESS" now-ns) || return 1
  printf 'new\n' >"$dir/new.pdf"
  printf 'ds\n' >"$dir/.DS_Store"
  listed=$(python3 "$HARNESS" new-since "$dir" "$epoch") || return 1
  [ "$listed" = "$dir/new.pdf" ]
  mkdir "$dir/locked"
  chmod 000 "$dir/locked"
  assert_fail python3 "$HARNESS" new-since "$dir" "$epoch"
  chmod u+rwx "$dir/locked"
}

check_readonly_wipe() {
  local outside before after
  create_run
  mkdir -p "$STATE_DIR/home/cache"
  printf 'x\n' >"$STATE_DIR/home/cache/ro"
  chmod a-w "$STATE_DIR/home/cache/ro"
  outside=$(mktemp -d "$SCRATCH/outside.XXXXXX")
  printf 'y\n' >"$outside/ro"
  chmod a-w "$outside/ro"
  chmod a-w "$outside"
  before=$(python3 "$HARNESS" mode "$outside")
  assert_fail python3 "$HARNESS" wipe "$outside" "$STATE_DIR"
  after=$(python3 "$HARNESS" mode "$outside")
  [ "$before" = "$after" ]
  python3 "$HARNESS" wipe "$STATE_DIR/home/cache" "$STATE_DIR" || return 1
  [ ! -e "$STATE_DIR/home/cache" ]
  chmod u+rwx "$outside" "$outside/ro" 2>/dev/null || true
}

check_prefs_recheck() {
  local prefs pid out line
  prefs="$SCRATCH/prefs-file"
  printf 'original\n' >"$prefs"
  PSYCH_CERT_VERIFY_PREFS_EXTRA=$prefs
  export PSYCH_CERT_VERIFY_PREFS_EXTRA
  create_run
  record_before_state || return 1
  load_env_args || return 1
  env -i "${ENV_ARGS[@]}" python3 -c 'import os; open(os.path.join(os.environ["HOME"], "touched"), "w").write("x")'
  compare_before_state || return 1
  [ -f "$STATE_DIR/home/touched" ]
  grep -x original "$prefs" >/dev/null
  python3 "$HARNESS" exec-setsid -- sleep 60 >>"$STATE_DIR/logs/sleep.log" 2>&1 &
  pid=$!
  note_pid "$pid"
  sleep 0.3
  python3 "$HARNESS" write-identity "$STATE_DIR/run.env" API "$pid" || return 1
  printf 'changed\n' >"$prefs"
  set +e
  out=$("$VERIFY" cleanup --id "$RUN_ID" 2>&1)
  local rc=$?
  set -e
  [ "$rc" -ne 0 ]
  line=$(last_line "$out")
  [ "$line" != "cleaned" ]
  if kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  unset PSYCH_CERT_VERIFY_PREFS_EXTRA
  printf 'original\n' >"$prefs"
}

check_darwin_home() {
  local out prefs
  create_run
  prefs="$SCRATCH/darwin-prefs"
  printf 'original\n' >"$prefs"
  out=$(PSYCH_CERT_VERIFY_ASSUME_UNAME=Darwin python3 "$HARNESS" child-env "$STATE_DIR") || return 1
  printf '%s\n' "$out" | grep -x "CFFIXED_USER_HOME=$STATE_DIR/home" >/dev/null
  printf '%s\n' "$out" | grep -x "HOME=$STATE_DIR/home" >/dev/null
  python3 "$HARNESS" record-before "$STATE_DIR/before-manifest" "$prefs" || return 1
  env -i HOME="$STATE_DIR/home" CFFIXED_USER_HOME="$STATE_DIR/home" PATH="$PATH" \
    python3 -c 'import os; open(os.path.join(os.environ["HOME"], "cf-touched"), "w").write("x")'
  [ -f "$STATE_DIR/home/cf-touched" ]
  grep -x original "$prefs" >/dev/null
  python3 "$HARNESS" compare-before "$STATE_DIR/before-manifest" "$prefs" || return 1
}

check_side_effects() {
  local log names
  log="$SCRATCH/effects.log"
  python3 "$HARNESS" side-effect "$log" tel "tel:100" || return 1
  python3 "$HARNESS" side-effect "$log" sms "sms:200" || return 1
  python3 "$HARNESS" side-effect "$log" mailto "mailto:person@example.com" || return 1
  names=$(python3 "$HARNESS" side-effect-names "$log") || return 1
  [ "$names" = $'tel\nsms\nmailto' ]
  python3 "$HARNESS" side-effect "$log" payment "payment:\$(touch $SCRATCH/pwned)" || return 1
  [ ! -e "$SCRATCH/pwned" ]
}

check_copy_tracked() {
  local repo dest
  repo=$(mktemp -d "$SCRATCH/src.XXXXXX")
  dest="$SCRATCH/sandbox-copy"
  git -C "$repo" init -q
  printf 'tracked\n' >"$repo/a.txt"
  git -C "$repo" add a.txt
  git -C "$repo" -c user.email=test@example.com -c user.name=Test commit -qm init
  mkdir -p "$repo/node_modules"
  printf 'junk\n' >"$repo/node_modules/junk.txt"
  printf 'loose\n' >"$repo/b.txt"
  ln -s /etc/passwd "$repo/outside-link"
  "$VERIFY" copy-sandbox "$repo" "$dest" || return 1
  [ -f "$dest/a.txt" ]
  [ ! -e "$dest/node_modules" ]
  [ ! -e "$dest/b.txt" ]
  [ ! -e "$dest/outside-link" ]
}

check_url_and_names() {
  python3 "$HARNESS" url-exact "http://127.0.0.1:1420/" "/" || return 1
  python3 "$HARNESS" url-exact "http://127.0.0.1:1420/health" "/health" || return 1
  assert_fail python3 "$HARNESS" url-exact "http://127.0.0.1:1420/wizard" "/"
  assert_fail python3 "$HARNESS" url-exact "http://127.0.0.1:1420/health-extra" "/health"
  assert_fail python3 "$HARNESS" url-exact "http://127.0.0.1:1420/health/" "/health"
  node "$BIN_DIR/ax-check.mjs" "$SCRATCH/ax" || return 1
}

check_exit_codes() {
  local rc
  set +e
  "$VERIFY" run -- false
  rc=$?
  set -e
  [ "$rc" -eq 1 ]
  set +e
  "$VERIFY" run -- /bin/sh -c 'exit 3'
  rc=$?
  set -e
  [ "$rc" -eq 3 ]
  "$VERIFY" run -- true
}

check_substitution_propagates() {
  helper_die() {
    exit 7
  }
  good() {
    local value
    value=$(helper_die) || return 1
    printf '%s' "$value"
  }
  assert_fail good
}

check_static_guards() {
  local files
  files="$BIN_DIR/lib.sh $BIN_DIR/regress.sh $BIN_DIR/verify-psych-cert-gen $BIN_DIR/harness.py $BIN_DIR/browser-server.mjs $BIN_DIR/ax-check.mjs"
  # shellcheck disable=SC2086
  if grep -n mapfile $files | grep -v 'grep -n mapfile'; then
    return 1
  fi
  # shellcheck disable=SC2086
  if grep -nE 'source .*run\.env|\. .*run\.env' $files | grep -v 'grep -nE'; then
    return 1
  fi
  # shellcheck disable=SC2086
  if grep -nE '(^|[^[:alnum:]_])eval[[:space:]]' $files | grep -v 'grep -nE'; then
    return 1
  fi
  forbidden=$(printf 'su%s' 'do')
  # shellcheck disable=SC2086
  if grep -n "$forbidden" $files; then
    return 1
  fi
  empty_array_ok
}

check_dest_guards() {
  local outside escaped evid
  create_run
  outside="$SCRATCH/outside"
  mkdir -p "$outside"
  escaped="$STATE_DIR/tmp/../../../outside/escaped.png"
  assert_fail node "$BIN_DIR/browser-server.mjs" --guard-write "$STATE_DIR" "$escaped"
  [ ! -e "$SCRATCH/outside/escaped.png" ]
  assert_fail node "$BIN_DIR/browser-server.mjs" --guard-write "$STATE_DIR" "$STATE_DIR/tmp/../escaped-in-state.png"
  [ ! -e "$STATE_DIR/escaped-in-state.png" ]
  ln -s "$outside/via-link.png" "$STATE_DIR/tmp/via-link.png"
  assert_fail node "$BIN_DIR/browser-server.mjs" --guard-write "$STATE_DIR" "$STATE_DIR/tmp/via-link.png"
  [ ! -e "$outside/via-link.png" ]
  ln -s "$outside" "$STATE_DIR/tmp/linked-dir"
  assert_fail node "$BIN_DIR/browser-server.mjs" --guard-write "$STATE_DIR" "$STATE_DIR/tmp/linked-dir/file.png"
  [ ! -e "$outside/file.png" ]
  ln -s "$outside/dangling.png" "$STATE_DIR/tmp/dangling.png"
  assert_fail node "$BIN_DIR/browser-server.mjs" --guard-write "$STATE_DIR" "$STATE_DIR/tmp/dangling.png"
  [ ! -e "$outside/dangling.png" ]
  node "$BIN_DIR/browser-server.mjs" --guard-write "$STATE_DIR" "$STATE_DIR/tmp/kept.png"
  [ -f "$STATE_DIR/tmp/kept.png" ]
  [ ! -e "$outside/kept.png" ]
  evid=$(python3 "$HARNESS" evidence-dir "$STATE_DIR") || return 1
  node "$BIN_DIR/browser-server.mjs" --guard-write "$STATE_DIR" "$evid/kept.txt"
  [ -f "$evid/kept.txt" ]
  if grep -n 'startsWith(`${state}' "$BIN_DIR/browser-server.mjs" || grep -n 'startsWith(state' "$BIN_DIR/browser-server.mjs"; then
    return 1
  fi
}

check_leftover_docx() {
  local out rc ninth
  create_run
  "$VERIFY" drive --id "$RUN_ID" cli-batch || return 1
  printf 'leftover\n' >"$STATE_DIR/output/cli/Leftover_Chen.docx"
  set +e
  out=$(python3 "$HARNESS" prove-pdfs "$STATE_DIR/output/cli" 0 "$STATE_DIR" 2>&1)
  rc=$?
  set -e
  [ "$rc" -ne 0 ]
  printf '%s\n' "$out" | grep -F 'Leftover_Chen.docx' >/dev/null
  rm -f "$STATE_DIR/output/cli/Leftover_Chen.docx"
  ninth=$(find "$STATE_DIR/output/cli" -name '*.pdf' -type f | sed -n '1p')
  [ -n "$ninth" ]
  cp "$ninth" "$STATE_DIR/output/cli/Ninth.pdf"
  assert_fail python3 "$HARNESS" prove-pdfs "$STATE_DIR/output/cli" 0 "$STATE_DIR"
  rm -f "$STATE_DIR/output/cli/Ninth.pdf"
}

check_no_residue() {
  local after
  after=$(git -C "$REPO" status --porcelain)
  [ "$after" = "$REPO_BEFORE" ]
}

check check_platform_before_dirs
check check_private_dirs
check check_run_env_literal
check check_home_not_from_state
check check_tool_path_not_from_state
check check_run_ids
check check_cleanup_requires_id
check check_failed_launch_kills
check check_mismatch_does_not_signal
check check_matching_cleanup
check check_ps_fail_closed
check check_live_pgid
check check_utc_lstart
check check_evidence_guards
check check_path_guards
check check_hash_unreadable
check check_new_files
check check_readonly_wipe
check check_prefs_recheck
check check_darwin_home
check check_side_effects
check check_copy_tracked
check check_url_and_names
check check_exit_codes
check check_substitution_propagates
check check_static_guards
check check_dest_guards
check check_leftover_docx
check check_no_residue

if [ "$FAIL" -ne 0 ]; then
  printf 'regression failed\n' >&2
  exit 1
fi
printf 'regression passed\n'
