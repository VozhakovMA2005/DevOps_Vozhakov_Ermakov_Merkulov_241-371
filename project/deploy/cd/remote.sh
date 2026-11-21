#!/usr/bin/env bash
set -euo pipefail
action="${1:-}"; tag="${2:-}"; commit="${3:-}"
case "$action" in deploy|rollback|recover|check) ;; *) echo 'Недопустимое действие' >&2; exit 1;; esac
if [[ "$action" == deploy && ! "$tag" =~ ^([0-9]+\.[0-9]+\.[0-9]+|sha-[0-9a-f]{40})$ ]]; then
  echo 'Недопустимый тег' >&2; exit 1
fi
[[ -z "$commit" || "$commit" =~ ^[0-9a-f]{40}$ ]] || exit 1
: "${CD_HOST:?Задайте CD_HOST}" "${CD_USER:?Задайте CD_USER}" "${CD_KEY:?Задайте CD_SSH_KEY}" "${CD_KNOWN_HOSTS:?Задайте CD_KNOWN_HOSTS}"
[[ "$CD_HOST" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ && "$CD_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] || exit 1
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
umask 077
printf '%s\n' "$CD_KEY" > "$tmp/key"
printf '%s\n' "$CD_KNOWN_HOSTS" > "$tmp/known_hosts"
ssh_opts=(-i "$tmp/key" -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$tmp/known_hosts" -o ConnectTimeout=10)
# The reviewed controller is installed on the host, not overwritten during rollback.
# No shell metacharacters survive the validation above.
command="python3 /opt/audfond-cd/cd.py $action --root /srv/audfond-staging"
if [[ "$action" == deploy ]]; then command+=" --tag $tag"; fi
if [[ -n "$commit" ]]; then command+=" --commit $commit"; fi
ssh "${ssh_opts[@]}" "$CD_USER@$CD_HOST" "$command"
