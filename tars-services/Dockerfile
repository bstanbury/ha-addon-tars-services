ARG BUILD_FROM
FROM ${BUILD_FROM}
RUN pip3 install flask requests tinytuya sseclient-py
COPY server.py /app/server.py
WORKDIR /app
ENTRYPOINT []
CMD ["python3", "server.py"]
