#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

# Scalar options + the users list are read from /data/options.json by the app.
if bashio::services.available "mqtt"; then
    export MQTT_HOST="$(bashio::services 'mqtt' 'host')"
    export MQTT_PORT="$(bashio::services 'mqtt' 'port')"
    export MQTT_USERNAME="$(bashio::services 'mqtt' 'username')"
    export MQTT_PASSWORD="$(bashio::services 'mqtt' 'password')"
    bashio::log.info "Using MQTT broker ${MQTT_HOST}:${MQTT_PORT}"
else
    bashio::log.fatal "No MQTT service available."
    bashio::log.fatal "Install the Mosquitto broker add-on and set up the MQTT integration."
    bashio::exit.nok
fi

bashio::log.info "Starting Beurer BF720 scale bridge..."
exec python3 /app/beurer_scale.py
