ARG BUILD_FROM
FROM ${BUILD_FROM}
RUN pip3 install flask requests tinytuya sseclient-py Pillow
COPY server.py /app/server.py
COPY helpers.py /app/helpers.py
COPY typed_config.py /app/typed_config.py
COPY sse_subscriber.py /app/sse_subscriber.py
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh
WORKDIR /app
ENTRYPOINT []
CMD ["/app/run.sh"]
