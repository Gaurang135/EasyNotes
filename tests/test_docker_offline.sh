#!/usr/bin/env bash
set -euo pipefail
docker rm -f easynotes_test 2>/dev/null || true
# --network none proves the offline-boot promise
docker run -d --name easynotes_test --network none -e SNAPSHOT_BACKEND=none easynotes:local
cleanup() { docker rm -f easynotes_test >/dev/null 2>&1 || true; }
trap cleanup EXIT
echo "waiting for boot (offline)…"
ok=0
for i in $(seq 1 30); do
  if docker exec easynotes_test python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)" 2>/dev/null; then
    ok=1; break
  fi
  sleep 2
done
[ "$ok" = 1 ] || { echo "FAIL: did not become healthy offline"; docker logs easynotes_test; exit 1; }
# ingest + search entirely inside the offline container
docker exec easynotes_test python - <<'PY'
import urllib.request
boundary = "X"
body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"n.txt\"\r\nContent-Type: text/plain\r\n\r\n").encode() \
       + b"refund policy for late payments" + f"\r\n--{boundary}--\r\n".encode()
req = urllib.request.Request("http://localhost:8000/documents", data=body,
                            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
print(urllib.request.urlopen(req).read().decode())
PY
sleep 3
if docker exec easynotes_test python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/search?q=refund&mode=hybrid').read().decode())" | grep -q refund; then
  echo "PASS: offline ingest + search works"
else
  echo "FAIL: search returned nothing"; exit 1
fi
