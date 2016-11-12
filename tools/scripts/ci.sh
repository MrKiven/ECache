#!/bin/bash

set -o pipefail
set +e
PYTHONPATH="`pwd`/tools/pylint:${PYTHONPATH}" pylint --rcfile tools/pylint/pylintrc ecache > pylint.log
exit $(($? & 2 ))
