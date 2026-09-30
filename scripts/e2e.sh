#!/bin/sh
# End-to-end check on a throw-away instance (ports 8101/8544, data in ./data-test): builds the image, runs the
# Playwright smoke test and, with --screenshots, creates demo data, trains a short run on the GPU and re-creates
# the README screenshots. --keep leaves the instance running afterwards.
set -e
cd "$(dirname "$0")/.."
SCREENSHOTS=0; KEEP=0
for arg in "$@"; do
  case "$arg" in
    --screenshots) SCREENSHOTS=1 ;;
    --keep) KEEP=1 ;;
    *) echo "usage: $0 [--screenshots] [--keep]"; exit 2 ;;
  esac
done
PORT="${TEST_PORT:-8101}"
COMPOSE="docker compose -p vt-test -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.test.yml"
PW="mcr.microsoft.com/playwright:v1.52.0-noble"
run_pw() { # script name, output dir
  docker run --rm --network host -v "$PWD/tests/e2e:/e2e" -v "$2:/out" -e BASE_URL="http://localhost:$PORT" -e OUT_DIR=/out "$PW" \
    sh -c "cd /tmp && npm init -y >/dev/null && npm i -s playwright@1.52.0 >/dev/null && cp /e2e/$1 /tmp/ && node /tmp/$1 && chown -R $(id -u):$(id -g) /out"
}

# fresh voices every run (the downloaded models in data-test/base are kept, they are large)
mkdir -p data-test
rm -rf data-test/voices data-test/current_voice
$COMPOSE up -d --build
for i in $(seq 1 90); do curl -sf "http://localhost:$PORT/api/health" >/dev/null && break; sleep 2; done
curl -sf "http://localhost:$PORT/api/health" >/dev/null || { echo "the test instance did not come up"; $COMPOSE logs --tail 50; exit 1; }

mkdir -p /tmp/vt-e2e-out
run_pw smoke.js /tmp/vt-e2e-out

if [ "$SCREENSHOTS" = "1" ]; then
  curl -sf -X POST "http://localhost:$PORT/api/voices" -H 'content-type: application/json' -d '{"name":"Anna","owner":"Anna Nováková","language":"cs"}' >/dev/null
  $COMPOSE exec -T app python /app/scripts/demo_dataset.py 150
  curl -sf -X PUT "http://localhost:$PORT/api/voice" -H 'content-type: application/json' \
    -d '{"training":{"epochs":40,"batch_size":16,"validation_every":5,"preview_every":10,"learning_rate":0.0001,"patience":0}}' >/dev/null
  curl -sf -X POST "http://localhost:$PORT/api/train" >/dev/null
  echo "training the demo voice..."
  while true; do
    status=$(curl -sf "http://localhost:$PORT/api/train" | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])')
    case "$status" in done|failed|cancelled) break ;; esac
    sleep 5
  done
  [ "$status" = "done" ] || { echo "demo training ended with $status"; exit 1; }
  run_pw screenshots.js "$PWD/docs/screenshots"
  echo "screenshots written to docs/screenshots"
fi

if [ "$KEEP" = "1" ]; then
  echo "test instance left running on http://localhost:$PORT (stop: $COMPOSE down)"
else
  $COMPOSE down
fi
