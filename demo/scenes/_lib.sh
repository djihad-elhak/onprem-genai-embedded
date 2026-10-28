# Helpers for the recorded demo scenes: type a command visibly, then run it.
cd "$(dirname "$0")/../.." || exit 1
source .venv/bin/activate
export COLUMNS=120 TERM=xterm-256color
say() { printf '\033[1;35m# %s\033[0m\n' "$1"; sleep 0.8; }
run() {
  printf '\033[1;32m$\033[0m '
  local text="$*"
  for ((i = 0; i < ${#text}; i++)); do printf '%s' "${text:i:1}"; sleep 0.012; done
  printf '\n'; sleep 0.3
  eval "$@"
  sleep 1.2
}
