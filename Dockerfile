FROM msagency/msa-image-python:1.0.2

# Install Redis
RUN apk --no-cache --update add redis

# Install the Python dependencies
ADD requirements.txt /opt/ms/
RUN apk add --virtual=build_dependencies \
    gcc \
    make \
    python3-dev \
    musl-dev \
    linux-headers \
    && pip install -r /opt/ms/requirements.txt \
    && apk del --purge -r build_dependencies \
    && rm -rf /tmp/build \
    && rm -rf /var/cache/apk/*

# Override the default endpoints
ADD README.md NAME LICENSE VERSION /opt/ms/
ADD swagger.json /opt/swagger/swagger.json

# Copy all the other application files to /opt/ms
ADD run.sh /opt/ms/
ADD app.py /opt/ms/

ADD redis.conf /opt/ms/

# Execute the run script
CMD ["ash", "/opt/ms/run.sh"]
