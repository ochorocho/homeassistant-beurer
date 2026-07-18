ARG BUILD_FROM
FROM ${BUILD_FROM}

# Python + BLE/MQTT deps. BlueZ runs on the host; the container only needs the
# D-Bus client (dbus-fast, pulled in by bleak) which talks over the mapped socket.
RUN apk add --no-cache python3 py3-pip

WORKDIR /app
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY beurer_scale.py /app/
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
