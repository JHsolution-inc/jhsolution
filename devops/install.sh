#!/bin/bash
set -Eeuo pipefail # exit on the failure

# Check certs

if [ ! -f ./nginx/certs/chain.pem ] || [ ! -f ./nginx/certs/key.pem ]; then
	echo cert file is missing
	exit
fi

# Docker installation in a debian way
# https://stackoverflow.com/q/45023363

apt-get -y update
apt-get -y dist-upgrade
apt-get -y install docker.io

# Docker volume creation

docker volume create postgresql-data
docker volume create jenkins-home
docker volume create lgtm-grafana
docker volume create lgtm-prometheus
docker volume create lgtm-loki
docker volume create protainer-data
docker volume create etc-nginx

# Run postgres

docker run -d --restart always --name postgres \
	-e POSTGRES_PASSWORD=$(hexdump -vn32 -e'8/4 "%08X" 1 "\n"' /dev/urandom) \
	-v postgresql-data:/var/lib/postgresql/data \
	postgres

# Run jenkins
# Note: grafana and portainer shares jenkins password for the initialization

docker run -d --restart always -m 1536M --name jenkins \
	-v jenkins-home:/var/jenkins_home \
	-v /usr/bin/docker:/usr/bin/docker \
	-v /var/run/docker.sock:/var/run/docker.sock \
	jenkins/jenkins:lts-jdk17

JENKINS_HOST=http://$(docker inspect --format '{{.NetworkSettings.IPAddress}}' jenkins):8080
INIT_PASS_PATH=/var/jenkins_home/secrets/initialAdminPassword
INIT_PASSWORD=$(docker exec jenkins sh -c "while [ ! -e ${INIT_PASS_PATH} ]; do sleep 0.1; done; cat ${INIT_PASS_PATH}")
docker exec -u root jenkins groupadd -g $(getent group docker | cut -d: -f3) docker
docker exec -u root jenkins usermod -aG docker jenkins
docker run --rm -v .:/infra -v jenkins-home:/var/jenkins_home busybox mkdir -p /var/jenkins_home/.ssh
docker run --rm -v .:/infra -v jenkins-home:/var/jenkins_home busybox sh -c "cat /infra/github_fingerprints >> /var/jenkins_home/.ssh/known_hosts"
docker restart jenkins

# Run lgtm stack

docker run -d --restart always --name otel-lgtm \
	-v lgtm-grafana:/data/grafana \
	-v lgtm-prometheus:/data/prometheus \
	-v lgtm-loki:/loki \
	grafana/otel-lgtm:latest

LGTM_HOST=http://$(docker inspect --format '{{.NetworkSettings.IPAddress}}' otel-lgtm):3000
while [ "$(wget -O - ${LGTM_HOST}/api/health | grep ok)" = "" ]; do
	sleep 1
done
docker exec otel-lgtm sh -c "cd /otel-lgtm/grafana-v*; ./bin/grafana cli admin reset-admin-password ${INIT_PASSWORD}"

# Run portainer

docker run -d --restart always --name portainer \
	-v protainer-data:/data \
	-v /var/run/docker.sock:/var/run/docker.sock \
	portainer/portainer-ce:latest

PORTAINER_HOST=https://$(docker inspect --format '{{.NetworkSettings.IPAddress}}' portainer):9443
DATA='{"Username":"admin","Password":"'${INIT_PASSWORD}'"}'
STAT_CHECK_COMMAND="wget -S -O /dev/null --no-check-certificate ${PORTAINER_HOST}/api/status"

while [ "$($STAT_CHECK_COMMAND 2>&1 | grep HTTP/ | awk '{print $2}')" != "200" ]; do
	sleep 1
done
wget -O /dev/null --no-check-certificate --method POST --body-data ${DATA} ${PORTAINER_HOST}/api/users/admin/init

# Run nginx

docker run -d --name nginx --restart always -p 80:80 -p 443:443 -v etc-nginx:/etc/nginx nginx

for f in $(ls -a ./nginx); do
	docker run --rm -v ./nginx:/etc/nginx -v etc-nginx:/etc_nginx busybox cp -rf /etc/nginx/$f /etc_nginx
done
docker run --rm -v etc-nginx:/etc/nginx busybox rm -rf /etc/nginx/conf.d/default.conf

docker exec nginx /etc/nginx/set_upstream application http://127.0.0.2:65535 # dummy
docker exec nginx /etc/nginx/set_upstream jenkins $JENKINS_HOST
docker exec nginx /etc/nginx/set_upstream grafana $LGTM_HOST
docker exec nginx /etc/nginx/set_upstream portainer $PORTAINER_HOST

docker exec nginx nginx -s reload

# Print credentials for initial setup

echo
echo
echo "####################################################################"
echo "####################################################################"
echo
echo "Initial admin password is: ${INIT_PASSWORD}"
echo
echo "####################################################################"
echo "####################################################################"
