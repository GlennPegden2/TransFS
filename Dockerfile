FROM python:3.10-slim

RUN apt-get update && apt-get install -y fuse samba    && pip install --no-cache-dir fusepy internetarchive requests pyyaml

# Add FUSE permission
RUN mkdir /mnt/transfs && chmod 755 /mnt/transfs

# Allow FUSE mount
RUN echo 'user_allow_other' >> /etc/fuse.conf

COPY . /app
WORKDIR /app

# Add a basic Samba config
COPY smb.conf /etc/samba/smb.conf

# Set up a Samba user (default user: smbuser, password: smbpass)
RUN useradd -M -s /sbin/nologin smbuser && \
    (echo "smbpass"; echo "smbpass") | smbpasswd -s -a smbuser

# Expose the default SMB port
EXPOSE 445

# Start Samba and the FUSE filesystem
CMD service smbd start && python3 transfs.py && tail -f /dev/null