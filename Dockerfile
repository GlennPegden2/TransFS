FROM python:3.10-slim


RUN apt-get update
RUN apt-get install -y fuse3 samba wget unzip libguestfs-tools p7zip unrar-free

COPY requirements.txt .
RUN pip install -r requirements.txt

# Install testing dependencies (for running tests in container)
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt

# Add FUSE permission
RUN mkdir /mnt/transfs && chmod 755 /mnt/transfs

# Allow FUSE mount
RUN echo 'user_allow_other' >> /etc/fuse.conf

# Add a basic Samba config
COPY smb.conf /etc/samba/smb.conf

# Set up a Samba user (default user: smbuser, password: smbpass)
RUN useradd -M -s /sbin/nologin smbuser && \
    (echo "smbpass"; echo "smbpass") | smbpasswd -s -a smbuser

# Expose the default SMB port
EXPOSE 445
EXPOSE 80

WORKDIR /app
#COPY ./app /app

# Start Samba and the FUSE filesystem
CMD service smbd start && \
    service nmbd start && \
    python3 -m transfs 2>&1 | tee /tmp/transfs.log & \
    WEB_PORT=$(python3 -c "import yaml; print(yaml.safe_load(open('transfs.yaml'))['web_api']['port'])" 2>/dev/null || echo "8000") && \
    WEB_HOST=$(python3 -c "import yaml; print(yaml.safe_load(open('transfs.yaml'))['web_api']['host'])" 2>/dev/null || echo "0.0.0.0") && \
    echo "Starting Web UI on ${WEB_HOST}:${WEB_PORT}" && \
    uvicorn main:app --host "${WEB_HOST}" --port "${WEB_PORT}" & \
    tail -f /dev/null