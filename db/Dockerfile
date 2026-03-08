FROM postgres:18

# Install build dependencies
RUN apt-get update && apt-get install -y \
    git \
    make \
    gcc \
    postgresql-server-dev-18 \
    && rm -rf /var/lib/apt/lists/*

# Clone and install pg_uuidv7
RUN git clone https://github.com/fboulnois/pg_uuidv7.git /tmp/pg_uuidv7 \
    && cd /tmp/pg_uuidv7 \
    && make \
    && make install \
    && rm -rf /tmp/pg_uuidv7
