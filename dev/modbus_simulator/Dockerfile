FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir pymodbus==3.12.1

COPY simulator.py /app/simulator.py

EXPOSE 502

ENV MODBUS_HOST=0.0.0.0
ENV MODBUS_PORT=502

CMD ["python", "/app/simulator.py"]
