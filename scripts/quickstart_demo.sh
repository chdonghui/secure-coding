#!/bin/sh

set -eu

SCRIPT_DIRECTORY=$(
  CDPATH= cd -- "$(dirname -- "$0")"
  pwd
)
REPOSITORY_ROOT=$(
  CDPATH= cd -- "${SCRIPT_DIRECTORY}/.."
  pwd
)

if ! command -v conda >/dev/null 2>&1; then
  echo 'Conda를 찾을 수 없습니다. Miniconda 설치와 셸 초기화를 확인하세요.' >&2
  exit 1
fi

CONDA_BASE=$(conda info --base)
SECURE_CODING_PYTHON="${CONDA_BASE}/envs/secure_coding/bin/python"
if [ ! -x "${SECURE_CODING_PYTHON}" ]; then
  echo 'secure_coding 환경을 찾을 수 없습니다.' >&2
  echo 'conda env create -f enviroments.yaml을 먼저 실행하세요.' >&2
  exit 1
fi

cd "${REPOSITORY_ROOT}"
exec "${SECURE_CODING_PYTHON}" \
  "${REPOSITORY_ROOT}/scripts/quickstart_demo.py" \
  "$@"
