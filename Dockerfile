# Build stage: extract chdman binary from mame-tools without bloating the final image
FROM python:3.10-slim AS chdman-builder
RUN apt-get update && \
    echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries && \
    apt-get install -y --no-install-recommends mame-tools

# Runtime image
FROM python:3.10-slim

COPY --from=chdman-builder /usr/bin/chdman /usr/bin/chdman

RUN apt-get update && \
    echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries && \
    apt-get install -y --no-install-recommends build-essential fuse3 libfuse3-dev pkg-config samba wget unzip libguestfs-tools p7zip unrar-free

COPY requirements.txt .
RUN pip install -r requirements.txt

# Add FUSE permission
RUN mkdir /mnt/transfs && chmod 755 /mnt/transfs

# Allow FUSE mount
RUN echo 'user_allow_other' >> /etc/fuse.conf

# Add a basic Samba config
COPY platform/linux/smb.conf /etc/samba/smb.conf
COPY platform/linux/smbusers /etc/samba/smbusers
COPY platform/linux/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Note: Samba user credentials are configured at app startup from app.yaml
# via app/smb_config.py, not at build time

# Expose the default SMB port
EXPOSE 445
EXPOSE 80

WORKDIR /app

ENTRYPOINT ["/entrypoint.sh"]