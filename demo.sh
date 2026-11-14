#!/usr/bin/env bash
# LiveQuiz Major Project – helper
#   ./demo.sh jenkins     start Jenkins (http://localhost:8088) – builds it the first time
#   ./demo.sh deploy      ONE CLICK: trigger the LiveQuiz-Deploy pipeline and stream it
#   ./demo.sh destroy     delete every AWS resource (LiveQuiz-Destroy pipeline)
#   ./demo.sh status      Jenkins, last builds, live URL, AWS resources
#   ./demo.sh url         print the live URL and the host (admin) password for the app
#   ./demo.sh logs [app|access|events|jenkins] [minutes]   show logs (default: all, last 30 min)
#   ./demo.sh stop        stop Jenkins (AWS is NOT touched – run destroy first)
set -uo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
SEC="$BASE/.secrets"; J=http://localhost:8088
say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m✔ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m✘ %s\033[0m\n' "$*"; exit 1; }
repo_url() { git -C "$BASE" remote get-url origin 2>/dev/null || die "No GitHub remote yet (git remote add origin ...)"; }
PW() { cat "$SEC/jenkins-admin-password"; }
api() { curl -s -u "admin:$(PW)" "$@"; }

trigger() {  # job [params...]
  local job=$1; shift
  local next jar crumb code
  next=$(api "$J/job/$job/api/json" | python3 -c 'import sys,json;print(json.load(sys.stdin)["nextBuildNumber"])') || die "Jenkins not running: ./demo.sh jenkins"
  jar=$(mktemp); crumb=$(curl -s -c "$jar" -u "admin:$(PW)" "$J/crumbIssuer/api/json" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["crumbRequestField"]+":"+d["crumb"])')
  if [ $# -gt 0 ]; then code=$(curl -s -b "$jar" -u "admin:$(PW)" -H "$crumb" -X POST "$J/job/$job/buildWithParameters" --data-urlencode "$1" -o /dev/null -w '%{http_code}')
  else code=$(curl -s -b "$jar" -u "admin:$(PW)" -H "$crumb" -X POST "$J/job/$job/build" -o /dev/null -w '%{http_code}'); fi
  rm -f "$jar"; [ "$code" = 201 ] || die "Jenkins refused to start $job (HTTP $code)"
  for _ in $(seq 1 60); do api -f -o /dev/null "$J/job/$job/$next/api/json" && break; sleep 2; done
  ok "$job #$next started: $J/job/$job/$next/"
  [ -n "${DEMO_NO_OPEN:-}" ] || open "$J/job/$job/$next/stages" 2>/dev/null || true
  local start=0 hdr; hdr=$(mktemp)
  while :; do
    api -D "$hdr" "$J/job/$job/$next/logText/progressiveText?start=$start" | perl -pe 's/\e\[8mha:\S*?\e\[0m//g' | grep -v '^\[Pipeline\]'
    start=$(grep -i '^X-Text-Size:' "$hdr" | tr -d '\r' | awk '{print $2}')
    grep -qi '^X-More-Data: true' "$hdr" || break; sleep 2
  done; rm -f "$hdr"
  local res; res=$(api "$J/job/$job/$next/api/json" | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"])')
  echo "RESULT: $res"; [ "$res" = SUCCESS ]
}

case "${1:-}" in
  jenkins)
    docker info >/dev/null 2>&1 || { open -a Docker; for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 3; done; }
    mkdir -p "$SEC"; chmod 700 "$SEC"
    [ -s "$SEC/jenkins-admin-password" ] || python3 -c 'import secrets;print(secrets.token_urlsafe(15),end="")' > "$SEC/jenkins-admin-password"
    chmod 600 "$SEC/jenkins-admin-password"
    # AWS: Jenkins reuses YOUR `aws login` session. credential_process lets Terraform refresh the short-lived keys itself.
    LS=$(aws configure get login_session 2>/dev/null) || die "Run 'aws login' first"
    printf '[profile user-login]\nlogin_session = %s\nregion = ap-south-1\n\n[default]\ncredential_process = aws configure export-credentials --profile user-login --format process\nregion = ap-south-1\n' "$LS" > "$SEC/aws-config"
    say "Building Jenkins image (first time ~3 min)"
    docker build -q -t livequiz-jenkins:1.0 "$BASE/jenkins" >/dev/null || die "image build failed"
    if docker inspect lq-jenkins >/dev/null 2>&1 && [ "$(docker inspect -f '{{.Image}}' lq-jenkins)" != "$(docker image inspect -f '{{.Id}}' livequiz-jenkins:1.0)" ]; then docker rm -f lq-jenkins >/dev/null; fi
    if ! docker inspect lq-jenkins >/dev/null 2>&1; then
      docker run -d --name lq-jenkins --restart unless-stopped -p 8088:8080 --group-add 0 \
        -e JENKINS_ADMIN_PASSWORD="$(PW)" -e LQ_REPO_URL="$(repo_url)" -e AWS_CONFIG_FILE=/run/lq/aws-config \
        -v lq-jenkins-home:/var/jenkins_home -v /var/run/docker.sock:/var/run/docker.sock \
        -v "$HOME/.aws/login":/var/jenkins_home/.aws/login -v "$SEC/aws-config":/run/lq/aws-config:ro \
        livequiz-jenkins:1.0 >/dev/null
    fi
    docker start lq-jenkins >/dev/null
    for _ in $(seq 1 90); do docker logs lq-jenkins 2>&1 | grep -q 'Jenkins is fully up' && break; sleep 2; done
    ok "Jenkins: $J   user: admin   password: cat .secrets/jenkins-admin-password"
    [ -n "${DEMO_NO_OPEN:-}" ] || open "$J/job/LiveQuiz-Deploy/" ;;
  deploy)  trigger LiveQuiz-Deploy && "$0" url ;;
  follow)  # stream the newest LiveQuiz-Deploy build (e.g. one started by a git push)
    n=$(api "$J/job/LiveQuiz-Deploy/lastBuild/api/json" | python3 -c 'import sys,json;print(json.load(sys.stdin)["number"])')
    start=0; hdr=$(mktemp)
    while :; do
      api -D "$hdr" "$J/job/LiveQuiz-Deploy/$n/logText/progressiveText?start=$start" | perl -pe 's/\e\[8mha:\S*?\e\[0m//g' | grep -v '^\[Pipeline\]'
      start=$(grep -i '^X-Text-Size:' "$hdr" | tr -d '\r' | awk '{print $2}'); grep -qi '^X-More-Data: true' "$hdr" || break; sleep 2
    done; rm -f "$hdr"; api "$J/job/LiveQuiz-Deploy/$n/api/json" | python3 -c 'import sys,json;print("RESULT:",json.load(sys.stdin)["result"])' ;;
  destroy) trigger LiveQuiz-Destroy CONFIRM=destroy ;;
  url)
    URL=$(docker exec lq-jenkins sh -c 'cd /var/jenkins_home/workspace/LiveQuiz-Deploy/infra/terraform 2>/dev/null && terraform output -raw app_url 2>/dev/null')
    [ -n "$URL" ] || die "Not deployed (run ./demo.sh deploy)"
    ok "LiveQuiz:      $URL"; ok "Players join:  $URL/play"
    ok "Host login:    admin / $(docker exec lq-jenkins cat /var/jenkins_home/state/admin-password)" ;;
  status)
    say "Jenkins"; docker ps --filter name=lq-jenkins --format '  {{.Names}} {{.Status}}'
    for j in LiveQuiz-Deploy LiveQuiz-Destroy; do printf '  %-18s ' $j; api "$J/job/$j/lastBuild/api/json" 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);print("#%s %s %s"%(d["number"],d["result"] or "RUNNING",d.get("description") or ""))' 2>/dev/null || echo '-'; done
    say "AWS (ap-south-1, tag Project=LiveQuiz)"
    aws ec2 describe-instances --filters Name=tag:Project,Values=LiveQuiz Name=instance-state-name,Values=pending,running,stopping,stopped \
      --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name,PublicIpAddress]' --output table 2>&1 | head -12 ;;
  logs)   # where: app (CloudWatch, everything) | access (CloudWatch HTTP requests) | events (CloudWatch logins/games) | jenkins (Jenkins access log)
    what=${2:-all}; mins=${3:-30}
    if [ "$what" = all ] || [ "$what" = access ]; then say "App access log – every HTTP request (AWS CloudWatch /livequiz/app, last ${mins} min)"
      aws logs tail /livequiz/app --since "${mins}m" --format short --filter-pattern '"HTTP/1.1"' | tail -25; fi
    if [ "$what" = all ] || [ "$what" = events ]; then say "App events – logins, games, players (AWS CloudWatch)"
      aws logs tail /livequiz/app --since "${mins}m" --format short --filter-pattern '"[livequiz]"' | tail -25; fi
    if [ "$what" = app ]; then say "App – all container output (AWS CloudWatch)"; aws logs tail /livequiz/app --since "${mins}m" --format short | tail -40; fi
    if [ "$what" = all ] || [ "$what" = jenkins ]; then say "Jenkins access log – every request to Jenkins (/var/jenkins_home/logs/access.log)"
      docker exec lq-jenkins tail -n 20 /var/jenkins_home/logs/access.log 2>/dev/null || echo "  (no access log yet)"; fi ;;
  stop) docker stop lq-jenkins >/dev/null && ok "Jenkins stopped (AWS untouched)" ;;
  *) sed -n '2,8p' "$0"; exit 1 ;;
esac
