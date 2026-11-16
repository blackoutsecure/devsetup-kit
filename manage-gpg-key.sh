#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=src/config.sh
. "$script_dir/src/config.sh"

audit=0
for arg in "$@"; do
	[[ "$arg" != "--audit" ]] || audit=1
done
devsetup_assert_execution_mode "$audit"

python=""
for candidate in "$script_dir/.venv/bin/python" python3 python; do
	if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
		python="$candidate"
		break
	fi
done
if [[ -z "$python" ]]; then
	printf 'Python 3.10 or later is required; run setup first.\n' >&2
	exit 1
fi
exec "$python" "$script_dir/src/manage-gpg-key.py" "$@"
