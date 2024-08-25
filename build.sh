#!/bin/bash
set -Eeuo pipefail # exit on the failure

# Check dockerfile update

GIT_HEAD=$(git rev-parse --short HEAD)
docker build -t jhsol-backend:$GIT_HEAD -t jhsol-backend:latest -f Dockerfile.deploy .
docker build -t jhsol-backend-test:$GIT_HEAD -t jhsol-backend-test:latest -f Dockerfile.test .

# Test the code

RUN_TEST="docker run --rm -v .:/build -w /build jhsol-backend-test:latest"
$RUN_TEST mypy
$RUN_TEST pytest --no-cov
$RUN_TEST find . -regex '^.*\(__pycache__\|\.py[co]\)$' -delete
$RUN_TEST rm -rf .mypy_cache .pytest_cache logs/log

# Complie scss

RUN_NODE="docker run --rm -v .:/build -w /build node:latest"
$RUN_NODE npm install --save-dev
$RUN_NODE npm run css
$RUN_NODE rm -r node_modules

# Deploy

mkdir -p application-archive
echo "*" > application-archive/.gitignore
git archive --format tar.gz -o application-archive/jhsol.tar.gz HEAD

[ "$(docker container ls -a | grep jhsol-backend)" ] && docker container rm -f jhsol-backend
docker container create --name jhsol-backend -w /application --env-file .env jhsol-backend:latest \
	python3 -m uvicorn jhsolution.main:app --host 0.0.0.0 --port 80

cat application-archive/jhsol.tar.gz | docker cp - jhsol-backend:/application
docker cp static/css/styles.css jhsol-backend:/application/static/css/styles.css
docker start jhsol-backend
